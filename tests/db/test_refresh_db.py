"""End-to-end refresh of the season in progress against a THROWAWAY PostgreSQL database and a fake league.

Covers: first ingestion, daily incremental ingestion, running twice, games after the cutoff, postponed games,
stat corrections (visible and invisible in the box score), a lagging source feed, NBA API timeouts, database
downtime, overlapping runs, freshness, and the frozen model scoring the season without future data.
Offline: no request reaches NBA.com; the real warehouse is never touched.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest

from nba_lineups.config import CURRENT_SEASON, PROJECT_ROOT, IngestSettings
from nba_lineups.ingest.specs import GAMELOG, LINEUPS
from nba_lineups.refresh import freshness, runner, schedule
from nba_lineups.refresh.lock import RefreshLock
from tests.refresh.fake_league import TEAM_IDS, FakeLeague, LeagueTransport

TOR = ZoneInfo("America/Toronto")
FAST = IngestSettings(min_interval_s=0, jitter_s=0, max_attempts=2, backoff_base_s=0.01, backoff_max_s=0.01)
START = date(2026, 10, 20)


def morning(d: date) -> datetime:
    """07:00 Toronto on day d: the scheduled run, whose cutoff is d - 1."""
    return datetime(d.year, d.month, d.day, 7, 0, tzinfo=TOR)


@pytest.fixture
def env(conn, test_db_url, tmp_path):
    league = FakeLeague()
    league.add_days(START, 8)                                   # Oct 20-27, every team plays daily

    class Env:
        def __init__(self):
            self.league, self.conn, self.data_dir = league, conn, tmp_path / "data"
            self.transport = LeagueTransport(league)
            self.db_up = True

        def connect(self):
            if not self.db_up:
                raise psycopg.OperationalError("connection refused (synthetic)")
            return psycopg.connect(test_db_url, autocommit=True)

        def run(self, day: date, **kw) -> runner.Outcome:
            self.transport.calls.clear()
            return runner.refresh(now=morning(day), data_dir=self.data_dir, transport_factory=lambda s: self.transport,
                                  connect_db=self.connect, settings=FAST,
                                  ingestor_kwargs={"sleep": lambda s: None}, **kw)

        def one(self, sql: str, *args):
            return self.conn.execute(sql, args).fetchone()

        def snapshot(self) -> list:
            return self.conn.execute("""SELECT l.team_id, l.player_key, s.window_type, s.poss, s.pts, s.opp_pts
                                        FROM lineup_window_stats s JOIN lineups l USING (lineup_id)
                                        ORDER BY 1, 2, 3""").fetchall()

    return Env()


def fetched_lineup_teams(e) -> set[int]:
    return {s.team_id for s in e.transport.calls if s.endpoint == LINEUPS}


def test_initial_ingestion_loads_the_season_to_date(env):
    out = env.run(date(2026, 10, 29))                           # cutoff Oct 28; games Oct 20-27
    assert out.status == runner.SUCCESS, out.message
    assert env.one("SELECT count(*) FROM team_games WHERE season_id = %s", CURRENT_SEASON)[0] == 8 * 30
    assert env.one("SELECT count(*) FROM lineups")[0] == 90
    assert env.one("SELECT window_type, date_from, date_to FROM stat_windows") == ("pre_asb", START, date(2026, 10, 27))
    r = env.one("SELECT status, data_cutoff, last_game_date, games_total FROM data_refreshes ORDER BY refresh_id DESC")
    assert r == ("success", date(2026, 10, 28), date(2026, 10, 27), 120)


def test_running_twice_creates_no_duplicates_and_requests_only_the_game_log(env):
    assert env.run(date(2026, 10, 29)).ok
    before = env.snapshot()
    out = env.run(date(2026, 10, 29))
    assert out.status == runner.NO_CHANGE
    assert [s.endpoint for s in env.transport.calls] == [GAMELOG]
    assert env.snapshot() == before
    assert env.one("SELECT count(*) FROM (SELECT game_id, team_id FROM team_games GROUP BY 1, 2 HAVING count(*) > 1) d")[0] == 0


def test_daily_incremental_refetches_only_teams_that_played(env):
    assert env.run(date(2026, 10, 29)).ok
    env.league.add_day(date(2026, 10, 28), TEAM_IDS[:10])       # 5 games, 10 teams
    out = env.run(date(2026, 10, 29) + timedelta(days=1))
    assert out.status == runner.SUCCESS and sorted(out.changed_teams) == TEAM_IDS[:10]
    assert fetched_lineup_teams(env) == set(TEAM_IDS[:10])
    assert env.one("SELECT count(*) FROM team_games")[0] == 8 * 30 + 10
    assert env.one("SELECT date_to FROM stat_windows")[0] == date(2026, 10, 28)


def test_games_after_the_cutoff_or_still_in_progress_are_never_loaded(env):
    env.league.add_day(date(2026, 10, 28))                      # played on the cutoff day...
    future = env.league.add_day(date(2026, 10, 30))             # ...and games after it (published early)
    env.league.in_progress = future[:1]
    env.league.games.remove(future[0])
    out = env.run(date(2026, 10, 29))                           # cutoff Oct 28
    assert out.ok
    assert env.one("SELECT max(game_date) FROM team_games")[0] == date(2026, 10, 28)
    assert env.one("SELECT max(date_to) FROM stat_windows")[0] <= out.data_cutoff


def test_postponed_game_is_absent_until_played_then_loaded_once(env):
    env.league.add_day(date(2026, 10, 28), TEAM_IDS[:28])       # TEAM 28 vs 29 postponed
    assert env.run(date(2026, 10, 29)).ok
    games_29 = env.one("SELECT count(*) FROM team_games WHERE team_id = %s", TEAM_IDS[29])[0]
    env.league.add_day(date(2026, 11, 2), TEAM_IDS[28:])        # make-up game
    out = env.run(date(2026, 11, 3))
    assert out.status == runner.SUCCESS and sorted(out.changed_teams) == TEAM_IDS[28:]
    assert env.one("SELECT count(*) FROM team_games WHERE team_id = %s", TEAM_IDS[29])[0] == games_29 + 1


def test_corrected_box_score_is_refetched_and_replaces_the_old_values(env):
    assert env.run(date(2026, 10, 29)).ok
    g = env.league.games[3]
    old = env.one("SELECT pts FROM team_games WHERE game_id = %s AND team_id = %s", g.game_id, g.home)[0]
    g.stints[1][0].fg3m += 1                                    # NBA corrects a missed 3 into a made 3
    g.stints[1][0].fgm += 1
    out = env.run(date(2026, 10, 30))
    assert out.status == runner.SUCCESS and sorted(out.changed_teams) == sorted([g.home, g.away])
    assert fetched_lineup_teams(env) == {g.home, g.away}
    assert env.one("SELECT pts FROM team_games WHERE game_id = %s AND team_id = %s", g.game_id, g.home)[0] == old + 3
    assert env.one("SELECT count(*) FROM team_games WHERE game_id = %s", g.game_id)[0] == 2


def test_correction_invisible_in_the_box_score_is_caught_by_the_sweep(env):
    assert env.run(date(2026, 10, 29)).ok
    g = env.league.games[5]
    a, b = g.stints[0][0], g.stints[1][0]                       # move a made 2 between two of the home lineups
    a.fgm, a.fga, b.fgm, b.fga = a.fgm - 1, a.fga - 1, b.fgm + 1, b.fga + 1
    before = env.snapshot()
    assert env.run(date(2026, 10, 30)).status == runner.NO_CHANGE       # box score unchanged: not detected daily
    assert env.snapshot() == before
    out = env.run(date(2026, 10, 30), full=True)                        # weekly sweep (or --full)
    assert out.status == runner.SUCCESS and out.full_sweep
    assert env.snapshot() != before


def test_weekly_sweep_runs_automatically(env):
    assert env.run(date(2026, 10, 29)).ok
    out = env.run(date(2026, 10, 29) + timedelta(days=runner.FULL_SWEEP_DAYS))
    assert out.full_sweep and len(fetched_lineup_teams(env)) == 30


def test_source_lag_fails_the_quality_gate_and_keeps_the_previous_data(env):
    assert env.run(date(2026, 10, 29)).ok
    before = env.snapshot()
    new = env.league.add_day(date(2026, 10, 29))
    env.league.lineup_lag = {new[0].game_id}                   # game log has it, lineup feed does not yet
    out = env.run(date(2026, 10, 30))
    assert out.status == runner.FAILED and "previous data kept" in out.message
    assert env.snapshot() == before
    assert env.one("SELECT max(game_date) FROM team_games")[0] == date(2026, 10, 27)
    env.league.lineup_lag = set()                              # the feed catches up
    assert env.run(date(2026, 10, 30)).status == runner.SUCCESS
    assert env.one("SELECT max(game_date) FROM team_games")[0] == date(2026, 10, 29)


def test_nba_api_timeouts_keep_the_previous_data_and_the_next_run_resumes(env):
    assert env.run(date(2026, 10, 29)).ok
    before = env.snapshot()
    env.league.add_day(date(2026, 10, 29))
    env.transport.fail = {LINEUPS: 10_000}                     # the lineup endpoint times out, all retries
    out = env.run(date(2026, 10, 30))
    assert out.status == runner.FAILED and out.summary.failed > 0
    assert env.snapshot() == before
    env.transport.fail = {}
    out = env.run(date(2026, 10, 30))
    assert out.status == runner.SUCCESS
    assert env.one("SELECT max(game_date) FROM team_games")[0] == date(2026, 10, 29)


def test_game_log_timeout_stops_before_any_other_request(env):
    env.transport.fail = {GAMELOG: 10_000}
    out = env.run(date(2026, 10, 29))
    assert out.status == runner.FAILED
    assert {s.endpoint for s in env.transport.calls} == {GAMELOG}
    assert len(env.transport.calls) == FAST.max_attempts


def test_database_down_makes_no_nba_requests_and_is_retried(env):
    env.db_up = False
    out = env.run(date(2026, 10, 29))
    assert out.status == runner.FAILED and "database unavailable" in out.message
    assert env.transport.calls == []
    state = schedule.LocalState.load(runner.Paths(env.data_dir).state_file)
    assert state.attempts_since_slot == 1 and state.last_success_at is None
    env.db_up = True
    out = runner.refresh(now=morning(date(2026, 10, 29)) + timedelta(hours=1), data_dir=env.data_dir,
                         transport_factory=lambda s: env.transport, connect_db=env.connect, settings=FAST,
                         only_if_due=True, ingestor_kwargs={"sleep": lambda s: None})
    assert out.status == runner.SUCCESS                         # the hourly catch-up succeeds


def test_overlapping_refresh_is_skipped(env):
    with RefreshLock(runner.Paths(env.data_dir).lock_file):
        out = env.run(date(2026, 10, 29))
    assert out.status == runner.LOCKED and env.transport.calls == []


def test_scheduled_mode_does_nothing_when_not_due(env):
    assert env.run(date(2026, 10, 29)).ok
    out = runner.refresh(now=morning(date(2026, 10, 29)) + timedelta(hours=3), data_dir=env.data_dir,
                         transport_factory=lambda s: env.transport, connect_db=env.connect, settings=FAST,
                         only_if_due=True)
    assert out.status == runner.NOT_DUE


def test_freshness_current_then_stale(env):
    assert env.run(date(2026, 10, 29)).ok
    with env.connect() as c:
        now = morning(date(2026, 10, 29)) + timedelta(hours=1)
        assert freshness.status(c, now)["freshness"] == "current"
        s = freshness.status(c, now + timedelta(days=1, hours=2))       # the next 07:00 run never happened
        assert s["freshness"] == "stale" and "expected through" in s["stale_reason"]
        v = freshness.data_version(c, CURRENT_SEASON)
    env.league.add_day(date(2026, 10, 28))
    assert env.run(date(2026, 10, 30)).status == runner.SUCCESS
    with env.connect() as c:
        assert freshness.data_version(c, CURRENT_SEASON) > v


def test_frozen_model_scores_the_season_without_future_data(env):
    """The served model's provisional predictions use only data up to the cutoff, are reproducible, and update
    after a refresh without a restart. The model itself is never changed."""
    from nba_lineups.api.services.predictions import FrozenPredictor

    pred = FrozenPredictor(PROJECT_ROOT / "models" / "final", PROJECT_ROOT / "reports" / "phase6")
    fingerprint = pred.parameters_fingerprint()
    assert env.run(date(2026, 10, 29)).ok
    with env.connect() as c:
        first = pred.season(c, CURRENT_SEASON).frame.predicted.copy()
    env.league.add_days(date(2026, 10, 29), 3)                  # games AFTER the cutoff appear at the source
    assert env.run(date(2026, 10, 29)).status == runner.NO_CHANGE
    with env.connect() as c:
        again = pred.season(c, CURRENT_SEASON)
        assert again.frame.predicted.equals(first)              # future games changed nothing
        assert again.data_cutoff == date(2026, 10, 27)
    assert env.run(date(2026, 10, 31)).status == runner.SUCCESS  # next day: through Oct 30
    with env.connect() as c:
        later = pred.season(c, CURRENT_SEASON)
        assert later.data_cutoff == date(2026, 10, 30)
        assert not later.frame.predicted.equals(first)          # picked up without restarting
    assert pred.parameters_fingerprint() == fingerprint and pred.verify()
