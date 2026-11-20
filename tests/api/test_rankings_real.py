"""Lineup rankings against the REAL warehouse: global order, thresholds, ties, paging, consistency with /lineups
and the prediction endpoints, and pre-cutoff-only predictions for the season in progress."""
from __future__ import annotations

from datetime import date

import pandas as pd
import psycopg
import pytest

from nba_lineups.config import CURRENT_SEASON

pytestmark = pytest.mark.realdata
V1 = "/api/v1"


def get(client, url, status=200):
    r = client.get(V1 + url)
    assert r.status_code == status, r.text
    return r.json()


def all_pages(client, path: str, page_size: int = 200) -> list[dict]:
    out, page = [], 1
    while True:
        d = get(client, f"{path}&page={page}&page_size={page_size}")
        out += d["items"]
        if page >= d["total_pages"]:
            return out
        page += 1


def sql(client, q: str, params=None) -> pd.DataFrame:
    with psycopg.connect(client.app.state.settings.database_url) as c:
        cur = c.execute(q, params)
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


def expected_ranks(df: pd.DataFrame, col: str, ascending: bool) -> pd.Series:
    return df.set_index("lineup_id")[col].astype(float).rank(method="min", ascending=ascending).astype(int)


@pytest.mark.parametrize("window, metric, min_poss", [("season", "net", 100), ("pre", "off", 200),
                                                      ("post", "def", 50), ("season", "poss", 0)])
def test_ranks_are_global_over_every_qualifying_lineup(client, window, metric, min_poss):
    items = all_pages(client, f"/rankings/lineups?season=2025-26&window={window}&metric={metric}&min_poss={min_poss}")
    view = ("SELECT lineup_id, poss, opp_poss, off_rating, def_rating, net_rating FROM v_lineup_season_ratings "
            "WHERE season_id = '2025-26'") if window == "season" else (
            "SELECT lineup_id, poss, opp_poss, off_rating, def_rating, net_rating FROM v_lineup_window_ratings "
            f"WHERE season_id = '2025-26' AND window_type = '{ {'pre': 'pre_asb', 'post': 'post_asb'}[window]}'")
    df = sql(client, view)
    col = {"net": "net_rating", "off": "off_rating", "def": "def_rating", "poss": "poss"}[metric]
    df = df[(df.poss.clip(upper=df.opp_poss.fillna(0)) >= min_poss) & df[col].notna()]
    assert len(items) == len(df) > 0
    want = expected_ranks(df, col, ascending=metric == "def")
    got = pd.Series({i["lineup_id"]: i["rank"] for i in items})
    assert got.sort_index().equals(want.sort_index())
    assert [i["rank"] for i in items] == sorted(i["rank"] for i in items)          # listed in rank order
    for i in items:
        assert min(i["poss"], i["opp_poss"] or 0) >= min_poss


def test_ties_share_a_rank_and_the_next_rank_skips(client):
    items = all_pages(client, "/rankings/lineups?season=2025-26&window=pre&metric=poss&min_poss=0")
    values = [i["poss"] for i in items]
    assert len(values) != len(set(values))                                          # there are ties to test
    for i in items:
        assert i["rank"] == 1 + sum(v > i["poss"] for v in values)
    tied = [i for i in items if values.count(i["poss"]) > 1][:2]
    assert tied[0]["rank"] == tied[1]["rank"]


def test_pages_continue_the_same_global_order(client):
    base = "/rankings/lineups?season=2025-26&window=season&metric=net&min_poss=100"
    one = get(client, f"{base}&page=1&page_size=50")["items"]
    two = get(client, f"{base}&page=2&page_size=25")["items"]
    first = get(client, f"{base}&page=1&page_size=25")["items"]
    assert [i["lineup_id"] for i in first + two] == [i["lineup_id"] for i in one]


def test_thresholds_shrink_the_field_monotonically(client):
    totals = [get(client, f"/rankings/lineups?season=2025-26&metric=net&min_poss={m}&page_size=1")["total"]
              for m in (0, 25, 100, 300)]
    assert totals == sorted(totals, reverse=True) and totals[-1] > 0


def test_consistent_with_the_lineups_endpoint(client):
    r = get(client, "/rankings/lineups?season=2025-26&window=pre&metric=net&min_poss=100&page_size=50")
    lu = get(client, "/lineups?season=2025-26&min_pre_poss=100&sort=pre_net&order=desc&page_size=50")
    assert r["total"] == lu["total"]
    assert [i["net_rating"] for i in r["items"]] == pytest.approx([i["pre_break"]["net_rating"] for i in lu["items"]])
    by_id = {i["lineup_id"]: i["pre_break"] for i in lu["items"]}
    for i in r["items"][:10]:
        if i["lineup_id"] in by_id:
            assert i["off_rating"] == pytest.approx(by_id[i["lineup_id"]]["off_rating"])
            assert i["minutes"] == pytest.approx(by_id[i["lineup_id"]]["minutes"])


def test_team_filter_and_small_sample_flags(client):
    r = get(client, "/rankings/lineups?season=2025-26&team_id=1610612750&metric=net&min_poss=0&page_size=200")
    assert r["items"] and {i["team_id"] for i in r["items"]} == {1610612750}
    assert r["items"][0]["rank"] == 1
    for i in r["items"]:
        assert i["small_sample"] == (min(i["poss"], i["opp_poss"] or 0) < 100)
        assert i["reliability"] is None or 0 <= i["reliability"] < 1


def test_window_labels_and_the_season_in_progress(client):
    full = get(client, "/rankings/lineups?season=2025-26&window=season&page_size=1")
    assert full["window_info"]["label"] == "Full season" and not full["provisional"]
    cur = get(client, f"/rankings/lineups?season={CURRENT_SEASON}&window=season&min_poss=0&page_size=1")
    if not cur["window_info"]["available"]:
        pytest.skip(f"{CURRENT_SEASON} not loaded")
    assert cur["window_info"]["label"] == "Season to date" and cur["provisional"]
    status = get(client, "/data-status")
    assert cur["window_info"]["date_to"] <= status["data_cutoff"]
    post = get(client, f"/rankings/lineups?season={CURRENT_SEASON}&window=post&page_size=1")
    if not post["window_info"]["available"]:                                   # break still ahead
        assert post["total"] == 0 and post["items"] == []


def test_unknown_season_or_team_is_404(client):
    get(client, "/rankings/lineups?season=1999-00", 404)
    get(client, "/rankings/lineups?season=2025-26&team_id=99", 404)
    get(client, "/rankings/predictions?season=1999-00", 404)


# ---------------------------------------------------------------- predictions

def test_prediction_ranking_matches_the_team_endpoint_and_the_lineup_prediction(client):
    r = get(client, "/rankings/predictions?season=2025-26&team_id=1610612750&min_pre_poss=50&page_size=200")
    t = get(client, "/teams/1610612750/predictions?season=2025-26&min_pre_poss=50&page_size=200")
    assert r["total"] == t["total"]
    assert [i["predicted_net_rating"] for i in r["items"]] == pytest.approx([i["predicted_net_rating"] for i in t["items"]])
    for i in r["items"][:3]:
        p = get(client, f"/lineups/{i['lineup_id']}/prediction?possessions=100")
        assert i["predicted_net_rating"] == pytest.approx(p["predicted_net_rating"])
        assert i["team_prior"] == pytest.approx(p["baselines"]["team_prior"])
        assert i["true_rating_interval_95"] == pytest.approx(p["uncertainty"]["true_rating_interval_95"])
        assert i["observed_rating_interval_95"] == pytest.approx(p["uncertainty"]["observed_rating_interval_95"])


def test_league_wide_prediction_ranking_is_global(client):
    items = all_pages(client, "/rankings/predictions?season=2025-26&min_pre_poss=100")
    preds = [i["predicted_net_rating"] for i in items]
    assert preds == sorted(preds, reverse=True) and len({i["team_id"] for i in items}) == 30
    best_per_team = max(get(client, f"/teams/{tid}/predictions?season=2025-26&min_pre_poss=100&page_size=1")
                        ["items"][0]["predicted_net_rating"] for tid in (1610612738, 1610612760, 1610612750))
    assert preds[0] >= best_per_team
    for i in items:
        assert min(i["pre_break_poss"], i["pre_break_opp_poss"]) >= 100 and i["kind"] == "recorded"
        assert i["rank"] == 1 + sum(p > i["predicted_net_rating"] for p in preds)


def test_prediction_ranking_discloses_uncertainty_and_the_baseline_verdict(client):
    r = get(client, "/rankings/predictions?season=2025-26&page_size=5")
    assert any("Not shown to beat the team-prior baseline" in n for n in r["notes"])
    assert any("not how many minutes" in n for n in r["notes"])
    assert r["interval_half_width"] == pytest.approx(1.959963984540054 * r["model_sd"])
    for i in r["items"]:
        assert i["true_rating_interval_95"]["hi"] - i["true_rating_interval_95"]["lo"] == pytest.approx(2 * r["interval_half_width"])
        assert i["model_minus_team_prior"] == pytest.approx(i["predicted_net_rating"] - i["team_prior"])
        assert not any("post" in k or "observed_post" in k for k in i)              # no realized outcome in the ranking


def test_current_season_prediction_ranking_is_provisional_and_pre_cutoff(client):
    r = get(client, f"/rankings/predictions?season={CURRENT_SEASON}&min_pre_poss=25&page_size=5")
    if not r["items"]:
        pytest.skip(f"{CURRENT_SEASON} not loaded")
    status = get(client, "/data-status")
    assert r["provisional"] and r["data_cutoff"] <= status["data_cutoff"]
    assert any(n.startswith("PROVISIONAL") for n in r["notes"])
    w = sql(client, "SELECT max(date_to) d FROM stat_windows WHERE season_id = %s", (CURRENT_SEASON,)).d.iloc[0]
    assert date.fromisoformat(r["data_cutoff"]) == w
    # pre-break possessions in the ranking equal the warehouse's pre-break totals (no other window is read)
    ids = [i["lineup_id"] for i in r["items"]]
    pre = sql(client, """SELECT lineup_id, poss FROM lineup_window_stats WHERE window_type = 'pre_asb'
                         AND lineup_id = ANY(%s)""", (ids,)).set_index("lineup_id").poss
    assert all(i["pre_break_poss"] == pre[i["lineup_id"]] for i in r["items"])
