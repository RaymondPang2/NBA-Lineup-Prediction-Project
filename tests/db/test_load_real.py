"""Integration test on REAL ingested data (one season) loaded into the throwaway test database.

Skipped when data/raw/2023-24 is absent (e.g. in CI, where raw NBA data is not available).
"""
import pytest

from nba_lineups.config import DEFAULT_DATA_DIR
from nba_lineups.etl.dq import ERROR
from nba_lineups.etl.extract import read_season
from nba_lineups.etl.load import load_season
from nba_lineups.etl.transform import transform_season

SEASON = "2023-24"
RAW = DEFAULT_DATA_DIR / "raw"
pytestmark = [pytest.mark.db, pytest.mark.realdata,
              pytest.mark.skipif(not (RAW / SEASON / "windows.json").exists(), reason="no ingested data")]


@pytest.fixture(scope="module")
def silver():
    return transform_season(read_season(RAW, SEASON))


def test_load_passes_all_error_checks_and_is_idempotent(conn, silver):
    counts1, dq = load_season(conn, silver)
    assert all(r.passed for r in dq if r.severity == ERROR), [r for r in dq if not r.passed]
    assert counts1["team_games"] == 2460 and counts1["team_window_stats"] == 60
    ids1 = conn.execute("SELECT lineup_id, player_key FROM lineups ORDER BY lineup_id").fetchall()

    counts2, _ = load_season(conn, silver)            # reload the same season
    ids2 = conn.execute("SELECT lineup_id, player_key FROM lineups ORDER BY lineup_id").fetchall()
    assert counts2 == counts1                          # same state
    assert ids2 == ids1                                # surrogate keys stable across reloads


def corrupted(points: int):
    bad = transform_season(read_season(RAW, SEASON))
    bad.tables["team_games"].loc[0, "pts"] += points       # corrupt one game's score
    bad.tables["team_games"].loc[0, "plus_minus"] += points
    return bad


def test_failed_quality_gate_rolls_back_everything(conn):
    from nba_lineups.etl.load import DataQualityError
    with pytest.raises(DataQualityError, match="points_reconcile"):
        load_season(conn, corrupted(10))                   # beyond the 2-point tolerance
    assert conn.execute("SELECT count(*) FROM lineup_window_stats").fetchone()[0] == 0  # nothing committed


def test_tiny_discrepancy_is_tolerated_but_reported(conn):
    # Like the real BKN @ DET case: the box score is consistent, but one lineup's total is off by a point.
    s = transform_season(read_season(RAW, SEASON))
    lws = s.tables["lineup_window_stats"]
    for col in ("ftm", "fta", "pts", "plus_minus"):        # one extra made free throw keeps pts = 2*fgm+fg3m+ftm
        lws.loc[0, col] += 1
    _, dq = load_season(conn, s)
    by = {r.name: r for r in dq}
    assert by["points_reconcile"].passed and not by["points_exact"].passed
