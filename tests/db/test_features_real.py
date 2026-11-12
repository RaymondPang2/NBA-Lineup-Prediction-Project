"""Feature pipeline on REAL data (2023-24) in the throwaway test database.

The key test is a "poisoning" test: build features, then add a DECOY held-out season (a relabelled copy
of 2023-24, so no real held-out data is loaded), delete every post-break row and blank last_team_id,
rebuild, and require identical features. If any feature read post-break, held-out or last_team_id data,
the result would change (or require_dev would raise).
"""
import pandas as pd
import pytest

from nba_lineups.config import DEFAULT_DATA_DIR
from nba_lineups.etl.extract import read_season
from nba_lineups.etl.load import load_season
from nba_lineups.etl.transform import transform_season
from nba_lineups.modeling import raw
from nba_lineups.modeling.features import FeatureBuilder

SEASON = "2023-24"
RAW = DEFAULT_DATA_DIR / "raw"
pytestmark = [pytest.mark.db, pytest.mark.realdata,
              pytest.mark.skipif(not (RAW / SEASON).exists(), reason="no ingested data for 2023-24")]


@pytest.fixture
def loaded(conn):
    load_season(conn, transform_season(read_season(RAW, SEASON)))
    return conn


def _features(conn, targets):
    tables = raw.load_pre_break_tables(conn, [SEASON])
    return FeatureBuilder().fit(tables, [SEASON]).transform(tables, targets)


def _add_decoy_held_out_season(conn) -> None:
    conn.execute("""
        INSERT INTO seasons SELECT '2024-25', 2024, false, first_game_date + 366, last_game_date + 366
          FROM seasons WHERE season_id = '2023-24';
        INSERT INTO stat_windows SELECT '2024-25', window_type, date_from + 366, date_to + 366
          FROM stat_windows WHERE season_id = '2023-24';
        INSERT INTO lineups (season_id, team_id, player_key)
          SELECT '2024-25', team_id, player_key FROM lineups WHERE season_id = '2023-24';
        CREATE TEMP TABLE id_map AS
          SELECT o.lineup_id AS old_id, n.lineup_id AS new_id FROM lineups o
          JOIN lineups n ON n.season_id = '2024-25' AND n.team_id = o.team_id AND n.player_key = o.player_key
          WHERE o.season_id = '2023-24';
        INSERT INTO lineup_players SELECT m.new_id, lp.player_id FROM lineup_players lp JOIN id_map m ON m.old_id = lp.lineup_id;
        CREATE TEMP TABLE lws AS SELECT * FROM lineup_window_stats WHERE season_id = '2023-24';
        UPDATE lws SET lineup_id = m.new_id, season_id = '2024-25' FROM id_map m WHERE m.old_id = lws.lineup_id;
        INSERT INTO lineup_window_stats SELECT * FROM lws;
        CREATE TEMP TABLE pws AS SELECT * FROM player_window_stats WHERE season_id = '2023-24';
        UPDATE pws SET season_id = '2024-25', usg_pct = 0.999;
        INSERT INTO player_window_stats SELECT * FROM pws;""")


def test_features_ignore_post_break_held_out_and_last_team_id(loaded):
    targets = raw.load_targets(loaded, [SEASON])
    assert len(targets) > 500
    clean = _features(loaded, targets)

    _add_decoy_held_out_season(loaded)
    assert loaded.execute("SELECT count(*) FROM lineup_window_stats WHERE season_id = '2024-25'").fetchone()[0] > 10_000
    loaded.execute("DELETE FROM lineup_window_stats WHERE window_type = 'post_asb'")
    loaded.execute("DELETE FROM player_window_stats WHERE window_type = 'post_asb'")
    loaded.execute("UPDATE player_window_stats SET last_team_id = NULL")
    poisoned = _features(loaded, targets)

    pd.testing.assert_frame_equal(clean, poisoned)
    with pytest.raises(raw.HeldOutDataError):
        raw.load_pre_break_tables(loaded, ["2024-25"])


def test_on_off_view_matches_the_python_derivation(loaded):
    tables = raw.load_pre_break_tables(loaded, [SEASON])
    view = pd.DataFrame(loaded.execute("""
        SELECT season_id, team_id, player_id, on_poss, on_opp_poss, on_pts, on_opp_pts,
               off_poss, off_opp_poss, off_pts, off_opp_pts
        FROM v_player_window_on_off WHERE window_type = 'pre_asb'""").fetchall(),
        columns=["season_id", "team_id", "player_id", "on_poss", "on_opp_poss", "on_pts", "on_opp_pts",
                 "off_poss", "off_opp_poss", "off_pts", "off_opp_pts"])
    py = tables.player_team[view.columns]
    key = ["season_id", "team_id", "player_id"]
    pd.testing.assert_frame_equal(view.sort_values(key).reset_index(drop=True).astype("int64", errors="ignore"),
                                  py.sort_values(key).reset_index(drop=True).astype("int64", errors="ignore"),
                                  check_dtype=False)
