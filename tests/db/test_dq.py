"""DQ check tests on tiny SYNTHETIC seeded data: each check must flag what it should and nothing else."""
import pytest

from nba_lineups.etl.dq import CHECKS, run_checks

pytestmark = pytest.mark.db
GAME_CHECK = tuple(c for c in CHECKS if c.name == "game_rows_consistent")


def seed_game(conn, home_a, home_b, won_a=True, pts=(110, 100)):
    conn.execute("""
        INSERT INTO seasons VALUES ('2024-25', 2024, false, '2024-10-22', '2025-04-13');
        INSERT INTO teams VALUES (1, 'AAA', 'A'), (2, 'BBB', 'B');""")
    conn.execute("INSERT INTO team_games VALUES ('g1', 1, '2024-25', '2024-12-14', %s, %s, 240, %s, %s)",
                 (home_a, won_a, pts[0], pts[0] - pts[1]))
    conn.execute("INSERT INTO team_games VALUES ('g1', 2, '2024-25', '2024-12-14', %s, %s, 240, %s, %s)",
                 (home_b, not won_a, pts[1], pts[1] - pts[0]))


@pytest.mark.parametrize("home_a,home_b,ok", [
    (True, False, True),     # normal game
    (None, None, True),      # neutral site (e.g. NBA Cup semifinal in Las Vegas)
    (True, True, False),     # two home teams
    (False, False, False),   # two away teams that are NOT marked neutral
    (True, None, False),     # neutral for one team only
])
def test_home_away_rules(conn, home_a, home_b, ok):
    seed_game(conn, home_a, home_b)
    assert run_checks(conn, "2024-25", GAME_CHECK)[0].passed is ok


def test_two_winners_flagged(conn):
    seed_game(conn, True, False)
    conn.execute("UPDATE team_games SET won = true")
    assert not run_checks(conn, "2024-25", GAME_CHECK)[0].passed
