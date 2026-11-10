"""Real-data metric tests (2023-24): SQL and Python definitions agree, and match NBA's published values.

Skipped without ingested data or PostgreSQL. Uses the throwaway test database.
"""
import numpy as np
import pandas as pd
import pytest

from nba_lineups import metrics
from nba_lineups.config import DEFAULT_DATA_DIR
from nba_lineups.etl.extract import read_season
from nba_lineups.etl.load import load_season
from nba_lineups.etl.transform import transform_season

SEASON = "2023-24"
RAW = DEFAULT_DATA_DIR / "raw"
pytestmark = [pytest.mark.db, pytest.mark.realdata,
              pytest.mark.skipif(not (RAW / SEASON / "windows.json").exists(), reason="no ingested data")]


@pytest.fixture
def loaded(conn):
    load_season(conn, transform_season(read_season(RAW, SEASON)))
    return conn


def frame(conn, sql):
    """Query -> DataFrame, converting PostgreSQL NUMERIC (Python Decimal) columns to float."""
    cur = conn.execute(sql)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for col in df.columns:
        if df[col].dtype == object:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass  # genuinely non-numeric (e.g. text) column
    return df


def test_sql_view_equals_python_metrics(loaded):
    v = frame(loaded, "SELECT pts, poss, opp_pts, opp_poss, off_rating, def_rating, net_rating "
                      "FROM v_lineup_window_ratings").astype(float)
    py = pd.DataFrame({
        "off": metrics.offensive_rating(v.pts, v.poss),
        "def": metrics.defensive_rating(v.opp_pts, v.opp_poss),
        "net": metrics.net_rating(v.pts, v.poss, v.opp_pts, v.opp_poss)})
    for ours, sql in (("off", "off_rating"), ("def", "def_rating"), ("net", "net_rating")):
        assert (py[ours].isna() == v[sql].isna()).all()                  # same rows undefined
        assert np.allclose(py[ours].dropna(), v[sql].dropna(), atol=1e-9)


def test_team_view_is_ratio_of_sums(loaded):
    lw = frame(loaded, "SELECT l.team_id, s.window_type, s.pts, s.poss, s.opp_pts, s.opp_poss "
                       "FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id)")
    lw = lw[lw.opp_poss.notna()].astype({"pts": float, "poss": float, "opp_pts": float, "opp_poss": float})
    py = metrics.aggregate_ratings(lw, ["team_id", "window_type"]).set_index(["team_id", "window_type"])
    sql = frame(loaded, "SELECT team_id, window_type, off_rating, def_rating FROM v_team_window_ratings"
                ).set_index(["team_id", "window_type"]).astype(float)
    joined = py.join(sql.add_suffix("_sql"))
    assert len(joined) == 60
    assert np.allclose(joined.def_rating, joined.def_rating_sql, atol=1e-9)


def test_every_unmerged_lineup_reproduces_nba_ratings(loaded):
    v = frame(loaded, "SELECT off_rating, def_rating, net_rating, nba_off_rating, nba_def_rating, nba_net_rating "
                      "FROM v_lineup_window_ratings WHERE n_source_rows = 1 AND poss > 0 AND opp_poss > 0").astype(float)
    assert len(v) > 15000
    for ours, nba in (("off_rating", "nba_off_rating"), ("def_rating", "nba_def_rating"), ("net_rating", "nba_net_rating")):
        assert (metrics.round_half_up(v[ours]) == v[nba]).all()


def test_opp_poss_is_known_whenever_time_was_played(loaded):
    n = loaded.execute("SELECT count(*) FROM lineup_window_stats WHERE seconds > 0 AND opp_poss IS NULL").fetchone()[0]
    assert n == 0
