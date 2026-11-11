"""Home/road location splits on REAL data (2023-24): reconciliation, rollback, cascade.

Skipped without ingested split files or PostgreSQL. Uses the throwaway test database.
"""
import pytest

from nba_lineups.config import DEFAULT_DATA_DIR
from nba_lineups.etl.extract import read_season
from nba_lineups.etl.load import load_season
from nba_lineups.etl.splits import (SplitReconciliationError, has_location_splits, load_location_splits,
                                    transform_location_splits)
from nba_lineups.etl.transform import transform_season

SEASON = "2023-24"
RAW = DEFAULT_DATA_DIR / "raw"
pytestmark = [pytest.mark.db, pytest.mark.realdata,
              pytest.mark.skipif(not has_location_splits(RAW, SEASON), reason="no ingested location splits")]


@pytest.fixture(scope="module")
def splits():
    return transform_location_splits(RAW, SEASON)


@pytest.fixture
def season_loaded(conn):
    load_season(conn, transform_season(read_season(RAW, SEASON)))
    return conn


def test_home_plus_road_reconciles_with_window_totals(season_loaded, splits):
    counts = load_location_splits(season_loaded, SEASON, splits)
    assert counts["lineup_split_stats"] == len(splits) > 10000
    # Independent re-check in SQL: possessions and points partition exactly.
    diff = season_loaded.execute("""
        SELECT sum(w.poss) - (SELECT sum(poss) FROM lineup_split_stats),
               sum(w.pts)  - (SELECT sum(pts)  FROM lineup_split_stats)
        FROM lineup_window_stats w WHERE w.window_type = 'pre_asb'""").fetchone()
    assert diff == (0, 0)


def test_corrupted_split_rolls_back(season_loaded, splits):
    load_location_splits(season_loaded, SEASON, splits)
    bad = splits.copy()
    i = bad.index[(bad.split == "home") & (bad.poss > 50)][0]
    bad.loc[i, ["pts", "plus_minus"]] += 1                    # one extra point in one home row
    with pytest.raises(SplitReconciliationError):
        load_location_splits(season_loaded, SEASON, bad)
    n = season_loaded.execute("SELECT count(*) FROM lineup_split_stats").fetchone()[0]
    assert n == len(splits)                                  # previous good load is intact


def test_reloading_the_season_cascades_its_splits(season_loaded, splits):
    load_location_splits(season_loaded, SEASON, splits)
    load_season(season_loaded, transform_season(read_season(RAW, SEASON)))
    assert season_loaded.execute("SELECT count(*) FROM lineup_split_stats").fetchone()[0] == 0
