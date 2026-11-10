"""Constraint tests: the database itself must reject impossible data.

Each test inserts one deliberately bad row and asserts the specific error class.
"""
import psycopg
import pytest
from psycopg import errors

pytestmark = pytest.mark.db


def seed(conn):
    conn.execute("""
        INSERT INTO seasons VALUES ('2023-24', 2023, false, '2023-10-24', '2024-04-14');
        INSERT INTO stat_windows VALUES ('2023-24', 'pre_asb', '2023-10-24', '2024-02-15'),
                                        ('2023-24', 'post_asb', '2024-02-22', '2024-04-14');
        INSERT INTO teams VALUES (1, 'AAA', 'Synthetic Team');
        INSERT INTO players VALUES (1, 'P1'), (2, 'P2'), (3, 'P3'), (4, 'P4'), (5, 'P5');
        INSERT INTO lineups (season_id, team_id, player_key) VALUES ('2023-24', 1, '1-2-3-4-5');
    """)
    return conn.execute("SELECT lineup_id FROM lineups").fetchone()[0]


# A valid stats row (synthetic): pts = 2*fgm + fg3m + ftm = 2*20+5+10 = 55; plus_minus = 55-50
VALID = dict(n_source_rows=1, gp=10, seconds=1200, poss=50, opp_poss_implied=50,
             fgm=20, fga=40, fg3m=5, fg3a=12, ftm=10, fta=12, oreb=3, dreb=10, ast=12, tov=6, pts=55,
             opp_fgm=20, opp_fga=45, opp_fg3m=4, opp_fg3a=14, opp_ftm=6, opp_fta=8, opp_oreb=4, opp_dreb=9,
             opp_tov=7, opp_pts=50, plus_minus=5)


def insert_stats(conn, lineup_id, season="2023-24", window="pre_asb", **overrides):
    row = VALID | overrides
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO lineup_window_stats (lineup_id, season_id, window_type, {cols}) "
                 f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(row))})", [lineup_id, season, window, *row.values()])


def test_valid_row_and_rating_view(conn):
    lid = seed(conn)
    insert_stats(conn, lid)
    off, deff, net = conn.execute("SELECT off_rating, def_rating, net_rating FROM v_lineup_window_ratings").fetchone()
    assert (float(off), float(deff), float(net)) == (110.0, 100.0, 10.0)


@pytest.mark.parametrize("overrides", [
    {"pts": 56},                 # breaks pts = 2*fgm + fg3m + ftm
    {"plus_minus": 4},           # breaks plus_minus = pts - opp_pts
    {"fg3m": 25, "fg3a": 30},    # more threes made than field goals made
    {"poss": -1},
    {"n_source_rows": 2, "nba_off_rating": 110.0},  # merged rows can't keep NBA ratings
])
def test_check_constraints(conn, overrides):
    lid = seed(conn)
    with pytest.raises(errors.CheckViolation):
        insert_stats(conn, lid, **overrides)


def test_overlapping_windows_are_rejected(conn):
    seed(conn)
    conn.execute("DELETE FROM stat_windows WHERE window_type = 'post_asb'")
    with pytest.raises(errors.ExclusionViolation):   # the in-database leakage guard
        conn.execute("INSERT INTO stat_windows VALUES ('2023-24', 'post_asb', '2024-02-10', '2024-04-14')")


def test_stats_season_must_match_lineup_season(conn):
    lid = seed(conn)
    conn.execute("""INSERT INTO seasons VALUES ('2022-23', 2022, false, '2022-10-18', '2023-04-09');
                    INSERT INTO stat_windows VALUES ('2022-23', 'pre_asb', '2022-10-18', '2023-02-16')""")
    with pytest.raises(errors.ForeignKeyViolation):  # composite FK (lineup_id, season_id)
        insert_stats(conn, lid, season="2022-23")


def test_orphans_and_duplicates_are_rejected(conn):
    lid = seed(conn)
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("INSERT INTO lineup_players VALUES (%s, 999)", (lid,))  # unknown player
    with pytest.raises(errors.UniqueViolation):
        conn.execute("INSERT INTO lineups (season_id, team_id, player_key) VALUES ('2023-24', 1, '1-2-3-4-5')")
    with pytest.raises(errors.CheckViolation):
        conn.execute("INSERT INTO lineups (season_id, team_id, player_key) VALUES ('2023-24', 1, '1-2-3-4')")


def test_deleting_a_window_cascades_to_its_stats(conn):
    lid = seed(conn)
    insert_stats(conn, lid)
    conn.execute("DELETE FROM stat_windows WHERE window_type = 'pre_asb'")
    assert conn.execute("SELECT count(*) FROM lineup_window_stats").fetchone()[0] == 0


def test_schema_is_idempotent(conn):
    from nba_lineups.db.connection import apply_schema
    apply_schema(conn)  # second application must not fail
    assert conn.execute("SELECT count(*) FROM seasons").fetchone()[0] == 0
