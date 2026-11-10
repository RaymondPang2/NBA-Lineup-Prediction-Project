"""Phase 3 metric validation report (read-only; queries the loaded database).

Sections 1-5 compare our metrics with NBA-published values (data QA, all seasons).
Sections 6-7 describe rating DISTRIBUTIONS and use development seasons only
(2018-19 .. 2023-24); 2024-25 and 2025-26 are held out from all analysis.

Usage:  .venv/bin/python scripts/phase3/validate_metrics.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from nba_lineups import metrics
from nba_lineups.db.connection import connect

DEV = "('2018-19','2019-20','2020-21','2021-22','2022-23','2023-24')"


def q(conn, sql: str) -> pd.DataFrame:
    cur = conn.execute(sql)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for c in df.columns:
        if df[c].dtype == object:
            try:
                df[c] = pd.to_numeric(df[c])
            except (ValueError, TypeError):
                pass
    return df


def section(t: str) -> None:
    print(f"\n=== {t}")


def main() -> None:
    pd.set_option("display.width", 160)
    with connect() as c:
        section("1. Canonical opponent possessions: method and coverage (all seasons)")
        print(q(c, """SELECT coalesce(opp_poss_method, 'UNKNOWN') AS method, count(*) AS rows,
                             count(*) FILTER (WHERE seconds = 0) AS zero_second_rows, sum(poss) AS own_poss
                      FROM lineup_window_stats GROUP BY 1 ORDER BY 2 DESC""").to_string(index=False))

        section("2. Route A (from DEF_RATING) vs canonical, un-merged rows, by sample size")
        print(q(c, """SELECT CASE WHEN poss < 25 THEN 'a: <25' WHEN poss < 100 THEN 'b: 25-99'
                                  WHEN poss < 300 THEN 'c: 100-299' ELSE 'd: 300+' END AS poss_bucket,
                             count(*) AS n, round(max(abs(opp_poss_implied - opp_poss)), 3) AS max_abs_diff,
                             round(avg(abs(opp_poss_implied - opp_poss)), 4) AS mean_abs_diff
                      FROM lineup_window_stats WHERE n_source_rows = 1 AND opp_poss_implied IS NOT NULL
                      GROUP BY 1 ORDER BY 1""").to_string(index=False))

        section("3. Reproduction of NBA-published lineup ratings (rounded half-up to 0.1)")
        r = q(c, """SELECT season_id,
                  count(*) FILTER (WHERE n_source_rows = 1 AND poss > 0 AND opp_poss > 0) AS compared,
                  count(*) FILTER (WHERE n_source_rows = 1 AND poss > 0 AND opp_poss > 0 AND (
                        round(per100(pts, poss), 1) <> nba_off_rating OR round(per100(opp_pts, opp_poss), 1) <> nba_def_rating
                     OR round(per100(pts, poss) - per100(opp_pts, opp_poss), 1) <> nba_net_rating)) AS mismatches,
                  count(*) FILTER (WHERE n_source_rows > 1) AS merged_no_nba_value,
                  count(*) FILTER (WHERE n_source_rows = 1 AND (poss = 0 OR opp_poss = 0 OR opp_poss IS NULL)) AS undefined_ours,
                  count(*) FILTER (WHERE n_source_rows = 1 AND poss = 0 AND pts > 0 AND nba_off_rating = 0) AS nba_reports_0_for_undefined
              FROM lineup_window_stats GROUP BY 1 ORDER BY 1""")
        print(r.to_string(index=False))
        print(f"TOTAL compared={r.compared.sum():,} mismatches={r.mismatches.sum()}")

        section("4. Team ratings from lineup totals vs team endpoint (all seasons; definitional difference)")
        t = q(c, """SELECT v.season_id, v.window_type, v.team_id, v.poss, v.opp_poss, v.off_rating, v.def_rating,
                           v.net_rating, tw.poss AS tw_poss, tw.off_rating AS tw_off, tw.def_rating AS tw_def,
                           tw.net_rating AS tw_net
                    FROM v_team_window_ratings v JOIN team_window_stats tw USING (season_id, window_type, team_id)""")
        for ours, theirs in (("off_rating", "tw_off"), ("def_rating", "tw_def"), ("net_rating", "tw_net")):
            d = t[ours] - t[theirs]
            print(f"  {ours:10s} ours - endpoint: mean={d.mean():+.2f}  sd={d.std():.2f}  min={d.min():+.2f}  max={d.max():+.2f}"
                  f"  corr={np.corrcoef(t[ours], t[theirs])[0, 1]:.4f}")
        print(f"  possession ratio lineup/endpoint: own median={np.median(t.poss / t.tw_poss):.3f}, "
              f"opp-to-own ratio (lineup feed) median={np.median(t.opp_poss / t.poss):.3f}  (n={len(t)} team-windows)")

        section("5. Player on-court (per team, from lineups) vs player endpoint, single-team players, >=500 poss")
        p = q(c, """WITH one_team AS (SELECT season_id, window_type, player_id FROM v_player_window_on_court
                                      GROUP BY 1, 2, 3 HAVING count(DISTINCT team_id) = 1)
                    SELECT o.*, pw.poss AS ep_poss, pw.off_rating AS ep_off, pw.def_rating AS ep_def, pw.net_rating AS ep_net
                    FROM v_player_window_on_court o JOIN one_team USING (season_id, window_type, player_id)
                    JOIN player_window_stats pw USING (season_id, window_type, player_id)
                    WHERE o.poss >= 500""")
        print(f"  n player-windows = {len(p):,}; possession ratio on-court/endpoint median={np.median(p.poss / p.ep_poss):.3f}")
        for ours, theirs in (("off_rating", "ep_off"), ("def_rating", "ep_def"), ("net_rating", "ep_net")):
            d = p[ours] - p[theirs]
            print(f"  {ours:10s} ours - endpoint: mean={d.mean():+.2f}  sd={d.std():.2f}  "
                  f"corr={np.corrcoef(p[ours], p[theirs])[0, 1]:.4f}")

        section("6. Small samples (development seasons only): how much do lineup ratings scatter?")
        s = q(c, f"""SELECT CASE WHEN poss < 25 THEN 'a: <25' WHEN poss < 100 THEN 'b: 25-99'
                                 WHEN poss < 300 THEN 'c: 100-299' ELSE 'd: 300+' END AS poss_bucket,
                            count(*) AS lineup_windows, sum(poss) AS total_poss,
                            round(stddev_samp(net_rating), 1) AS sd_net,
                            round(avg((abs(net_rating) > 50)::int), 3) AS share_abs_net_gt_50
                     FROM v_lineup_window_ratings WHERE season_id IN {DEV} AND net_rating IS NOT NULL
                     GROUP BY 1 ORDER BY 1""")
        s["share_of_poss"] = (s.total_poss / s.total_poss.sum()).round(3)
        print(s.to_string(index=False))

        section("7. Mean of ratios vs ratio of sums (development seasons, team pre-break ORtg)")
        lw = q(c, f"""SELECT l.season_id, l.team_id, s.pts, s.poss FROM lineup_window_stats s
                      JOIN lineups l USING (lineup_id, season_id)
                      WHERE s.season_id IN {DEV} AND s.window_type = 'pre_asb' AND s.poss > 0""")
        lw["ortg"] = metrics.offensive_rating(lw.pts, lw.poss)
        g = lw.groupby(["season_id", "team_id"])
        ratio_of_sums = 100 * g.pts.sum() / g.poss.sum()
        mean_of_ratios = g.ortg.mean()
        print(f"  team-seasons={len(ratio_of_sums)} | ratio of sums: mean={ratio_of_sums.mean():.1f} sd={ratio_of_sums.std():.1f}"
              f" | unweighted mean of lineup ratios: mean={mean_of_ratios.mean():.1f} sd={mean_of_ratios.std():.1f}"
              f" | mean |difference| = {(ratio_of_sums - mean_of_ratios).abs().mean():.1f} points per 100")


if __name__ == "__main__":
    main()
