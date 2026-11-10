"""Sample-size report from the database (after ETL). Read-only.

Unit of analysis = a post-All-Star-break lineup (the conditional target sample).
Eligible for the primary feature set = all 5 players logged pre-break possessions
for the SAME team in the SAME season (so player-level pre-break features exist).

Split (chronological; 2025-26 is reserved for the final out-of-sample test):
    train 2018-19 .. 2023-24   |   validation 2024-25   |   final test 2025-26

Usage:  .venv/bin/python scripts/phase2/sample_size_report.py
"""
from __future__ import annotations

import math
from statistics import NormalDist

from nba_lineups.db.connection import connect

SPLITS = {"train": ["2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"],
          "validation": ["2024-25"], "test (final)": ["2025-26"]}
IRREGULAR = {"2019-20", "2020-21"}

SQL = """
WITH pre_players AS (            -- (season, team, player) with pre-break possessions
    SELECT DISTINCT l.season_id, l.team_id, lp.player_id
    FROM lineup_window_stats s
    JOIN lineups l USING (lineup_id, season_id)
    JOIN lineup_players lp USING (lineup_id)
    WHERE s.window_type = 'pre_asb' AND s.poss > 0),
post AS (                        -- post-break lineups + how many of their players have pre-break data
    SELECT s.lineup_id, l.season_id, s.poss,
           count(pp.player_id) AS n_with_pre
    FROM lineup_window_stats s
    JOIN lineups l USING (lineup_id, season_id)
    JOIN lineup_players lp USING (lineup_id)
    LEFT JOIN pre_players pp ON pp.season_id = l.season_id AND pp.team_id = l.team_id AND pp.player_id = lp.player_id
    WHERE s.window_type = 'post_asb'
    GROUP BY s.lineup_id, l.season_id, s.poss)
SELECT p.season_id, t.min_poss,
       count(*)                                                     AS n_all,
       count(*) FILTER (WHERE n_with_pre = 5)                       AS n_eligible,
       sum(poss) FILTER (WHERE n_with_pre = 5)                      AS sum_w,
       sum(poss::numeric * poss) FILTER (WHERE n_with_pre = 5)      AS sum_w2
FROM post p CROSS JOIN (VALUES (25), (50)) AS t(min_poss)
WHERE p.poss >= t.min_poss
GROUP BY p.season_id, t.min_poss
ORDER BY t.min_poss, p.season_id
"""


def n_for_r(r: float, alpha: float = 0.05, power: float = 0.8) -> int:
    z = NormalDist().inv_cdf
    return math.ceil(((z(1 - alpha / 2) + z(power)) / math.atanh(r)) ** 2 + 3)


def main() -> None:
    with connect() as conn:
        rows = conn.execute(SQL).fetchall()
    by = {(s, m): (n_all, n_el, float(w or 0), float(w2 or 0)) for s, m, n_all, n_el, w, w2 in rows}
    seasons = sorted({s for s, _ in by})
    for min_poss in (25, 50):
        print(f"\n=== post-break lineups with >= {min_poss} possessions ===")
        print(f"{'season':9s} {'all':>6s} {'eligible':>9s} {'eff_n':>7s}")
        for s in seasons:
            n_all, n_el, w, w2 = by.get((s, min_poss), (0, 0, 0.0, 0.0))
            flag = "  (irregular)" if s in IRREGULAR else ""
            print(f"{s:9s} {n_all:6d} {n_el:9d} {w * w / w2 if w2 else 0:7.0f}{flag}")
        print("-- by split (effective n of the pooled split)")
        for split, ss in SPLITS.items():
            for label, keep in (("all seasons", ss), ("excl. irregular", [s for s in ss if s not in IRREGULAR])):
                if label == "excl. irregular" and keep == ss:
                    continue
                w = sum(by.get((s, min_poss), (0, 0, 0, 0))[2] for s in keep)
                w2 = sum(by.get((s, min_poss), (0, 0, 0, 0))[3] for s in keep)
                n = sum(by.get((s, min_poss), (0, 0, 0, 0))[1] for s in keep)
                print(f"   {split:13s} {label:16s} n={n:5d}  eff_n={w * w / w2 if w2 else 0:6.0f}")
    print("\npower (alpha=.05, 80%): r=0.15 ->", n_for_r(0.15), "| r=0.20 ->", n_for_r(0.20), "| r=0.25 ->", n_for_r(0.25))


if __name__ == "__main__":
    main()
