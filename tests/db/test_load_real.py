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
    # Like the real BKN @ DET case (game 0022500704): the box score credits a team with 1 point that no
    # lineup has. Both game rows stay consistent: team +1 pts and +1 margin, opponent -1 margin.
    s = transform_season(read_season(RAW, SEASON))
    tg = s.tables["team_games"]
    game = tg.loc[0, "game_id"]
    opp_row = tg.index[(tg.game_id == game) & (tg.index != 0)][0]
    tg.loc[0, ["pts", "plus_minus"]] += 1
    tg.loc[opp_row, "plus_minus"] -= 1
    _, dq = load_season(conn, s)
    by = {r.name: r for r in dq}
    assert by["points_reconcile"].passed and by["game_rows_consistent"].passed
    assert not by["points_exact"].passed and not by["plus_minus_exact"].passed
