"""Reconcile the Power BI dataset and the measures (reference implementations) against the source of truth.

Needs the export (scripts/phase9/export_powerbi.py → data/powerbi/) and, for the warehouse comparisons, the
running PostgreSQL. The warehouse is only READ here. Skipped when either is missing.

Sources of truth:
  PostgreSQL views (v_team_window_ratings, v_lineup_window_ratings, team_games)   ratings, totals, records
  reports/phase6/holdout/holdout_findings.json                                     model metrics (4 decimals)
  reports/phase4/findings.json                                                     selection (continuation)
  docs/api.md example (lineup 281112)                                              a single prediction
"""
from __future__ import annotations

import json
import zipfile
from functools import cache

import numpy as np
import pandas as pd
import psycopg
import pytest

from nba_lineups.bi import model as bim
from nba_lineups.bi.export import DEFAULT_OUT, WORKBOOK
from nba_lineups.bi.reference import Filter, Model, load
from nba_lineups.config import DEV_SEASONS, HELDOUT_SEASONS, PROJECT_ROOT
from nba_lineups.db.connection import database_url

CSV = DEFAULT_OUT / "csv"
pytestmark = [pytest.mark.realdata,
              pytest.mark.skipif(not (CSV / "fact_prediction.csv").exists(), reason="run scripts/phase9/export_powerbi.py first")]
MIN = 1610612750


@pytest.fixture(scope="module")
def data():
    return load(CSV)


@pytest.fixture(scope="module")
def m(data) -> Model:
    return Model(data)


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(database_url(), connect_timeout=3)
    except (RuntimeError, psycopg.OperationalError) as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    c.read_only = True
    yield c
    c.close()


def q(conn, sql, params=None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


@cache
def holdout() -> dict:
    return json.loads((PROJECT_ROOT / "reports/phase6/holdout/holdout_findings.json").read_text())["evaluations"]


# ------------------------------------------------------------------------------------------------ shape & integrity

def test_columns_and_types_match_the_semantic_model(data):
    for t in bim.data_tables():
        assert list(data[t.name].columns) == [c.name for c in t.columns], t.name
        for c in t.columns:
            s = data[t.name][c.name]
            if not c.nullable:
                assert s.notna().all(), f"{t.name}.{c.name} has blanks"


def test_keys_are_unique_and_relationships_have_no_orphans(data):
    for t, key in [("dim_season", ["season_id"]), ("dim_team", ["team_id"]), ("dim_player", ["player_id"]),
                   ("dim_window", ["window_type"]), ("dim_lineup", ["lineup_id"]), ("bridge_lineup_player", ["lineup_id", "player_id"]),
                   ("fact_lineup_window", ["lineup_id", "window_type"]), ("fact_team_window", ["season_id", "team_id", "window_type"]),
                   ("fact_prediction", ["lineup_id"])]:
        assert not data[t].duplicated(key).any(), f"{t}: duplicate {key}"
    for r in bim.RELATIONSHIPS:
        many, one = data[r.from_table][r.from_column], data[r.to_table][r.to_column]
        assert one.is_unique, f"{r.to_table}.{r.to_column} must be unique (one side)"
        assert many.isin(one).all(), f"{r.from_table}.{r.from_column} has values missing from {r.to_table}"


def test_every_lineup_has_exactly_five_players(data):
    assert (data["bridge_lineup_player"].groupby("lineup_id").size() == 5).all()
    assert set(data["bridge_lineup_player"].lineup_id) == set(data["dim_lineup"].lineup_id)


def test_row_counts_match_the_warehouse(data, conn):
    counts = q(conn, """SELECT (SELECT count(*) FROM lineups) l, (SELECT count(*) FROM lineup_players) lp,
                               (SELECT count(*) FROM lineup_window_stats) lws, (SELECT count(*) FROM teams) t,
                               (SELECT count(*) FROM seasons) s""").iloc[0]
    assert len(data["dim_lineup"]) == counts.l and len(data["bridge_lineup_player"]) == counts.lp
    assert len(data["fact_lineup_window"]) == counts.lws and len(data["dim_team"]) == counts.t and len(data["dim_season"]) == counts.s


def test_manifest_and_parameters_name_the_frozen_model(data):
    spec = json.loads((PROJECT_ROOT / "models/final/frozen_spec.json").read_text())
    manifest = json.loads((DEFAULT_OUT / "manifest.json").read_text())
    p = data["model_parameters"].iloc[0]
    assert p.artifact_sha256 == spec["artifact"]["sha256"] == manifest["model_artifact_sha256"]
    assert p.k_noise == pytest.approx(14639, abs=1) and p.min_target_poss == 25


def test_excel_workbook_holds_every_table_as_an_excel_table(data):
    """Power BI imports Excel *tables*; check names and row ranges without loading 29 MB of cells."""
    with zipfile.ZipFile(DEFAULT_OUT / WORKBOOK) as z:
        tables = {}
        for n in z.namelist():
            if n.startswith("xl/tables/"):
                x = z.read(n).decode()
                name = x.split(' name="', 1)[1].split('"', 1)[0]
                ref = x.split(' ref="', 1)[1].split('"', 1)[0]
                tables[name] = int("".join(ch for ch in ref.split(":")[1] if ch.isdigit())) - 1
    for t in bim.data_tables():
        assert tables[t.name] == max(len(data[t.name]), 1), t.name
    assert "_Measures" in tables


# ------------------------------------------------------------------------------------------------ ratings & totals

def test_team_ratings_equal_the_warehouse_view_for_every_team_season_window(m, conn):
    v = q(conn, """SELECT season_id, window_type, team_id, poss, pts, off_rating::float8 o, def_rating::float8 d,
                          net_rating::float8 n FROM v_team_window_ratings""")
    assert len(v) == 480
    for r in v.itertuples():
        f = Filter(seasons=[r.season_id], teams=[r.team_id], window=r.window_type)
        assert m.possessions(f) == r.poss
        assert m.ortg(f) == pytest.approx(r.o, abs=1e-9)
        assert m.drtg(f) == pytest.approx(r.d, abs=1e-9)
        assert m.net(f) == pytest.approx(r.n, abs=1e-9)


def test_every_lineup_window_rating_equals_the_warehouse_including_missing_opponent_possessions(m, conn):
    v = q(conn, "SELECT lineup_id, window_type, net_rating::float8 n FROM v_lineup_window_ratings").set_index(["lineup_id", "window_type"])
    x = m.d["fact_lineup_window"].copy()
    x["net"] = np.where((x.poss > 0) & (x.opp_poss > 0),
                        100 * x.pts / x.poss.where(x.poss > 0) - 100 * x.opp_pts_rated / x.opp_poss.where(x.opp_poss > 0), np.nan)
    j = x.set_index(["lineup_id", "window_type"]).join(v)
    both = j.n.notna() & j.net.notna()
    assert np.allclose(j.net[both], j.n[both], atol=1e-9)
    assert (j.n.isna() == j.net.isna()).all(), "Net Rating must be blank exactly where the warehouse rating is undefined"
    assert j.n.isna().sum() >= 162                      # the lineup-windows with no opponent possessions


def test_season_totals(m, conn):
    v = q(conn, """SELECT l.season_id, sum(s.poss) poss, sum(s.pts) pts, sum(s.seconds)/60.0 minutes
                   FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id) GROUP BY 1""")
    for r in v.itertuples():
        x = m.flw(Filter(seasons=[r.season_id]))
        assert x.poss.sum() == r.poss and x.pts.sum() == r.pts
        assert x.minutes.sum() == pytest.approx(float(r.minutes), rel=1e-9)


def test_win_loss_records_match_game_logs(m, conn):
    v = q(conn, """SELECT g.season_id, g.team_id, count(*) games, count(*) FILTER (WHERE g.won) wins
                   FROM team_games g GROUP BY 1, 2""")
    for r in v.itertuples():
        games, wins, losses = m.record(Filter(seasons=[r.season_id], teams=[r.team_id]))
        # the two windows exclude only All-Star-break days, which have no games
        assert (games, wins) == (r.games, r.wins) and games == wins + losses


def test_pooled_rating_is_not_the_average_of_lineup_ratings(m):
    """Why the measures divide sums: averaging lineup ratings is dominated by tiny samples."""
    f = Filter(seasons=["2025-26"], window="pre_asb")
    pooled, weighted, simple = m.net(f), m.lineup_net_avg_weighted(f), m.lineup_net_avg_unweighted(f)
    assert abs(weighted - pooled) < 1.0          # weighting by possessions gets close to the pooled value
    assert abs(simple - pooled) > 3 * abs(weighted - pooled)


# ------------------------------------------------------------------------------------------------ player filters

def test_player_filter_counts_each_lineup_once(m, conn):
    """Selecting two teammates: the model sums each lineup once; a naive join through the bridge double counts
    lineups that contain both players."""
    players = [1630162, 1630183]                         # Edwards, McDaniels (MIN)
    f = Filter(seasons=["2025-26"], players=players, window="pre_asb")
    correct = q(conn, """SELECT sum(poss) p FROM v_lineup_window_ratings WHERE season_id = '2025-26' AND window_type = 'pre_asb'
                         AND lineup_id IN (SELECT lineup_id FROM lineup_players WHERE player_id = ANY(%s))""", (players,)).p[0]
    naive = q(conn, """SELECT sum(r.poss) p FROM v_lineup_window_ratings r JOIN lineup_players lp USING (lineup_id)
                       WHERE r.season_id = '2025-26' AND r.window_type = 'pre_asb' AND lp.player_id = ANY(%s)""", (players,)).p[0]
    assert m.possessions(f) == correct
    assert naive > correct                                # the double counting the bridge design prevents


def test_all_selected_players_semantics(m, conn):
    players = [1630162, 1630183]
    f = Filter(seasons=["2025-26"], players=players, players_mode="all")
    ids = q(conn, """SELECT lineup_id FROM lineup_players lp JOIN lineups l USING (lineup_id)
                     WHERE l.season_id = '2025-26' AND player_id = ANY(%s)
                     GROUP BY lineup_id HAVING count(*) = 2""", (players,)).lineup_id
    assert m.lineups(f) == len(ids) > 0
    assert m.lineups(f) < m.lineups(Filter(seasons=["2025-26"], players=players))


def test_player_on_court_totals_equal_the_warehouse_view(m, conn):
    v = q(conn, """SELECT player_id, sum(poss) poss, sum(pts) pts FROM v_player_window_on_court
                   WHERE season_id = '2024-25' AND window_type = 'pre_asb' GROUP BY player_id ORDER BY poss DESC LIMIT 25""")
    for r in v.itertuples():
        x = m.flw(Filter(seasons=["2024-25"], players=[r.player_id], window="pre_asb"))
        assert (x.poss.sum(), x.pts.sum()) == (r.poss, r.pts)


# ------------------------------------------------------------------------------------------------ uncertainty

def test_sampling_se_matches_the_api_example(m):
    # docs/api.md: lineup 281112, pre-break 1,183 possessions, net +10.0 (sampling SD 5.0); change SD 10.8
    f = Filter(lineups=[281112])
    assert m.net_se(f, "pre_asb") == pytest.approx(4.97377, abs=1e-4)
    assert np.hypot(m.net_se(f, "pre_asb"), m.net_se(f, "post_asb")) == pytest.approx(10.7746, abs=1e-3)
    assert m.change_exceeds_noise(f) == 0


def test_reliability_measure_reproduces_the_models_per_lineup_reliability(m):
    fp = m.d["fact_prediction"]
    sample = fp[fp.pre_no_history == 0].sample(400, random_state=1)
    for r in sample.itertuples():
        assert m.reliability(Filter(lineups=[r.lineup_id]), "pre_asb") == pytest.approx(r.pre_reliability, abs=1e-9)
    assert (fp.loc[fp.pre_no_history == 1, "pre_reliability"] == 0).all()


# ------------------------------------------------------------------------------------------------ model performance

@pytest.mark.parametrize("evaluation", ["2024-25", "2025-26", "pooled"])
def test_model_metrics_reproduce_the_held_out_evaluation(m, evaluation):
    seasons = list(HELDOUT_SEASONS) if evaluation == "pooled" else [evaluation]
    got = m.model_metrics(Filter(seasons=seasons))
    ref = holdout()[evaluation]
    k = ref["metrics"]
    assert got["n"] == ref["n"]
    pairs = {"model_rmse": "linear|weighted|rmse", "team_prior_rmse": "team_prior|weighted|rmse",
             "league_mean_rmse": "league_mean|weighted|rmse", "model_mae": "linear|weighted|mae",
             "team_prior_mae": "team_prior|weighted|mae", "league_mean_mae": "league_mean|weighted|mae",
             "model_r2": "linear|weighted|r2", "noise_floor_rmse": "noise_floor|weighted|rmse_floor",
             "r2_ceiling": "noise_floor|weighted|r2_ceiling", "skill_vs_team_prior": "linear|weighted|skill_tp"}
    for ours, theirs in pairs.items():
        assert round(got[ours], 4) == k[theirs][0], f"{evaluation} {ours}: {got[ours]:.4f} vs {k[theirs][0]}"


def test_documented_prediction(data):
    r = data["fact_prediction"].set_index("lineup_id").loc[281112]
    assert r.predicted_net == pytest.approx(5.894, abs=1e-3) and r.team_prior_net == pytest.approx(6.1126, abs=1e-3)
    assert r.observed_post_net == pytest.approx(0.0672, abs=1e-3) and r.in_evaluation_sample == 1
    assert r.evaluation_set == "Held-out test" and r.is_training_season == 0


def test_prediction_rows_cover_every_post_break_lineup(data, conn):
    n = q(conn, "SELECT count(*) n FROM lineup_window_stats WHERE window_type = 'post_asb' AND poss > 0").n[0]
    fp = data["fact_prediction"]
    assert len(fp) == n and fp.predicted_net.notna().all() and fp.team_prior_net.notna().all()
    assert set(fp.loc[fp.is_training_season == 1, "season_id"]) == set(DEV_SEASONS)
    missing = fp.observed_post_net.isna()
    assert (fp.loc[missing, "post_opp_poss"] == 0).all() and (fp.loc[missing, "in_evaluation_sample"] == 0).all()


def test_prediction_deciles_cover_only_the_evaluation_sample(data):
    fp = data["fact_prediction"]
    ev = fp.in_evaluation_sample == 1
    assert fp.loc[ev, "predicted_decile"].between(1, 10).all() and fp.loc[~ev, "predicted_decile"].isna().all()


# ------------------------------------------------------------------------------------------------ selection

def test_continuation_reproduces_the_phase4_selection_analysis(m):
    p4 = json.loads((PROJECT_ROOT / "reports/phase4/findings.json").read_text())
    got = m.selection(Filter(seasons=list(DEV_SEASONS)))
    assert got["population"] == p4["continuation_population"]["n"] == 8120
    assert got["continuation_rate"] == pytest.approx(p4["continuation_population"]["continues_rate"], abs=1e-9)
    assert got["appearance_rate"] == pytest.approx(p4["continuation_population"]["appears_rate"], abs=1e-9)
    dl = m.d["dim_lineup"].set_index("lineup_id")
    for b in p4["continuation_by_possessions"]:
        label = b["poss_bin"].replace("10000)", "+)")
        ids = dl.index[dl.pre_poss_bin == label]
        s = m.selection(Filter(seasons=list(DEV_SEASONS), lineups=list(ids)))
        assert s["population"] == b["n"], label
        assert round(s["continuation_rate"], 4) == b["continues"] and round(s["appearance_rate"], 4) == b["appears"], label


def test_selection_measures_respect_team_filters(m):
    a = m.selection(Filter(seasons=["2025-26"], teams=[MIN]))
    b = m.selection(Filter(seasons=["2025-26"]))
    assert 0 < a["population"] < b["population"]
