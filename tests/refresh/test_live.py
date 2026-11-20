"""Season in progress: cutoff, trimming, windows, per-team requests, change detection. Offline, synthetic."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from nba_lineups.config import CURRENT_SEASON
from nba_lineups.ingest import live
from nba_lineups.ingest.specs import LINEUPS, gamelog_spec, season_specs
from nba_lineups.ingest.validate import validate_payload
from nba_lineups.ingest.windows import POST, PRE, live_windows
from tests.refresh.fake_league import TEAM_IDS, FakeLeague

ET = ZoneInfo("America/New_York")
TOR = ZoneInfo("America/Toronto")


@pytest.mark.parametrize("now, cutoff", [
    (datetime(2026, 11, 20, 7, 0, tzinfo=TOR), date(2026, 11, 19)),     # the scheduled run: yesterday
    (datetime(2026, 11, 20, 0, 30, tzinfo=ET), date(2026, 11, 18)),     # just after midnight: late games may be live
    (datetime(2026, 11, 20, 5, 59, tzinfo=ET), date(2026, 11, 18)),
    (datetime(2026, 11, 20, 6, 0, tzinfo=ET), date(2026, 11, 19)),
    (datetime(2026, 11, 20, 12, 0, tzinfo=ZoneInfo("UTC")), date(2026, 11, 19)),
    (datetime(2027, 3, 14, 7, 0, tzinfo=TOR), date(2027, 3, 13)),       # DST change day
])
def test_data_cutoff_is_yesterday_once_games_are_final(now, cutoff):
    assert live.data_cutoff(now) == cutoff


def test_data_cutoff_requires_an_aware_datetime():
    with pytest.raises(ValueError):
        live.data_cutoff(datetime(2026, 11, 20, 7))


def _league(days: int = 5) -> FakeLeague:
    lg = FakeLeague()
    lg.add_days(date(2026, 10, 20), days)
    return lg


def test_games_after_the_cutoff_and_unfinished_games_are_dropped():
    lg = _league(5)
    lg.in_progress = [g for g in lg.add_day(date(2026, 10, 24))[:1]]       # a game of the cutoff day still live
    lg.games.remove(lg.in_progress[0])
    payload = lg.answer(gamelog_spec(CURRENT_SEASON))
    games = live.completed_games(payload, cutoff=date(2026, 10, 23))
    assert games.GAME_DATE.max() == "2026-10-23"
    assert len(games) == 4 * 30
    games = live.completed_games(payload, cutoff=date(2026, 10, 24))
    assert lg.in_progress[0].game_id not in set(games.GAME_ID)
    assert (games.groupby("GAME_ID").size() == 2).all()


def test_windows_before_and_after_the_break():
    pre_only = live_windows(CURRENT_SEASON, [date(2026, 10, 20), date(2026, 11, 18)])
    assert list(pre_only) == [PRE] and pre_only[PRE].date_to == date(2026, 11, 18)
    days = [date(2027, 2, d) for d in (10, 11, 12)] + [date(2027, 2, 18), date(2027, 2, 19)]
    both = live_windows(CURRENT_SEASON, days)
    assert both[PRE].date_to == date(2027, 2, 12) and both[POST].date_from == date(2027, 2, 18)
    with pytest.raises(ValueError):
        live_windows(CURRENT_SEASON, [])


def test_plan_requests_end_at_each_teams_last_game_and_never_after_the_cutoff():
    lg = _league(3)
    lg.add_day(date(2026, 10, 23), TEAM_IDS[:10])                         # only 10 teams play on the last day
    lg.add_days(date(2026, 10, 25), 2)                                    # after the cutoff
    p = live.plan(CURRENT_SEASON, lg.answer(gamelog_spec(CURRENT_SEASON)), cutoff=date(2026, 10, 23))
    assert p.windows[PRE].date_to == date(2026, 10, 23)
    specs = season_specs(CURRENT_SEASON, p.windows, p.team_ids, p.team_last)
    lineup_to = {s.team_id: s.kwargs["date_to_nullable"] for s in specs if s.endpoint == LINEUPS}
    assert lineup_to[TEAM_IDS[0]] == "10/23/2026" and lineup_to[TEAM_IDS[20]] == "10/22/2026"
    assert all(s.kwargs.get("date_to_nullable", "10/23/2026") <= "10/23/2026" for s in specs)


def test_unchanged_team_reuses_its_request_and_a_team_that_played_does_not():
    lg = _league(3)
    day1 = live.plan(CURRENT_SEASON, lg.answer(gamelog_spec(CURRENT_SEASON)), date(2026, 10, 22))
    lg.add_day(date(2026, 10, 23), TEAM_IDS[:10])
    day2 = live.plan(CURRENT_SEASON, lg.answer(gamelog_spec(CURRENT_SEASON)), date(2026, 10, 23))
    s1 = {s.key: s for s in season_specs(CURRENT_SEASON, day1.windows, day1.team_ids, day1.team_last) if s.endpoint == LINEUPS}
    s2 = {s.key: s for s in season_specs(CURRENT_SEASON, day2.windows, day2.team_ids, day2.team_last) if s.endpoint == LINEUPS}
    same = {k for k in s1 if s1[k] == s2[k]}
    assert {s2[k].team_id for k in s2 if k not in same} == set(TEAM_IDS[:10])
    # an old cached file still validates for an unchanged team, and is rejected for a team that played
    played = next(k for k in s2 if s2[k].team_id == TEAM_IDS[0])
    rested = next(k for k in s2 if s2[k].team_id == TEAM_IDS[20])
    assert validate_payload(s2[rested], lg.answer(s1[rested])).ok
    assert not validate_payload(s2[played], lg.answer(s1[played])).ok


def test_fingerprints_detect_new_and_corrected_games_only_for_affected_teams():
    lg = _league(3)
    fp1 = live.team_fingerprints(live.completed_games(lg.answer(gamelog_spec(CURRENT_SEASON)), date(2026, 10, 22)))
    g = lg.games[0]
    g.stints[0][0].fgm += 1                                               # stat correction to an old game
    g.stints[0][0].fga += 1
    fp2 = live.team_fingerprints(live.completed_games(lg.answer(gamelog_spec(CURRENT_SEASON)), date(2026, 10, 22)))
    assert {t for t in fp1 if fp1[t] != fp2[t]} == {g.home, g.away}


def test_live_validation_accepts_a_partial_team_list_but_completed_seasons_do_not():
    from nba_lineups.ingest.specs import team_specs
    lg = FakeLeague()
    lg.add_days(date(2027, 2, 10), 3)
    lg.add_day(date(2027, 2, 18), TEAM_IDS[:6])                            # first day after the break: 6 teams
    p = live.plan(CURRENT_SEASON, lg.answer(gamelog_spec(CURRENT_SEASON)), date(2027, 2, 18))
    spec = next(s for s in team_specs(CURRENT_SEASON, p.windows) if s.window == POST)
    payload = lg.answer(spec)
    assert len(payload["resultSets"][0]["rowSet"]) == 6
    assert validate_payload(spec, payload).ok
    assert {t for (w, t) in p.team_last if w == POST} == set(TEAM_IDS[:6])   # no lineup request for idle teams
    completed = type(spec)(spec.endpoint, "2025-26", spec.params, spec.window, spec.measure)
    assert not validate_payload(completed, payload).ok
