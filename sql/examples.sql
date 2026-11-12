-- Example queries on the silver layer. Run with:
--   docker exec -i nba_lineups_db psql -U nba -d nba_lineups < sql/examples.sql

-- 1) JOIN + filter + ORDER BY: best pre-break lineups with a meaningful sample (>= 300 possessions).
--    Ratings come from the view, which applies the denominator contract (ORtg/own poss, DRtg/opp poss).
\echo '--- 1. Top pre-break lineups, 2023-24 (>= 300 poss)'
-- Ratings in the view are exact; round only when displaying.
SELECT abbreviation AS team, poss, opp_poss, round(off_rating, 1) AS ortg, round(def_rating, 1) AS drtg,
       round(net_rating, 1) AS net
FROM v_lineup_window_ratings
WHERE season_id = '2023-24' AND window_type = 'pre_asb' AND poss >= 300
ORDER BY net_rating DESC
LIMIT 5;

-- 2) Bridge table: every lineup that contains a given player, with player names aggregated per lineup.
\echo '--- 2. Most-used lineups containing the player with the most pre-break lineup possessions (2023-24)'
WITH top_player AS (
    SELECT lp.player_id
    FROM lineup_window_stats s JOIN lineup_players lp USING (lineup_id)
    WHERE s.season_id = '2023-24' AND s.window_type = 'pre_asb'
    GROUP BY lp.player_id ORDER BY sum(s.poss) DESC LIMIT 1)
SELECT r.abbreviation AS team, r.poss, round(r.net_rating, 1) AS net,
       string_agg(p.player_name, ', ' ORDER BY p.player_name) AS players
FROM v_lineup_window_ratings r
JOIN lineup_players lp ON lp.lineup_id = r.lineup_id
JOIN players p USING (player_id)
WHERE r.season_id = '2023-24' AND r.window_type = 'pre_asb'
  AND r.lineup_id IN (SELECT lineup_id FROM lineup_players WHERE player_id = (SELECT player_id FROM top_player))
GROUP BY r.lineup_id, r.abbreviation, r.poss, r.net_rating
ORDER BY r.poss DESC LIMIT 3;

-- 3) Window functions: how concentrated is each team's playing time in its single most-used lineup?
--    SUM(...) OVER (PARTITION BY team) gives the team total on every row without collapsing rows.
\echo '--- 3. Share of team minutes played by each team''s top lineup (2023-24 full season, top 5 teams)'
WITH per_lineup AS (
    SELECT l.team_id, l.lineup_id, sum(s.seconds) AS secs
    FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id)
    WHERE s.season_id = '2023-24' GROUP BY 1, 2),
ranked AS (
    SELECT team_id, secs,
           secs / sum(secs) OVER (PARTITION BY team_id) AS share,
           row_number() OVER (PARTITION BY team_id ORDER BY secs DESC) AS rn
    FROM per_lineup)
SELECT t.abbreviation AS team, round(100 * share, 1) AS top_lineup_pct_of_minutes
FROM ranked JOIN teams t USING (team_id)
WHERE rn = 1 ORDER BY share DESC LIMIT 5;

-- 4) Aggregate-then-divide: team ratings built from lineup TOTALS (same possession definition as the
--    lineups) next to the team endpoint's own numbers, which use a different possession count.
\echo '--- 4. Team ORtg from lineup totals vs team endpoint (2023-24 pre-break, 5 teams)'
SELECT t.abbreviation AS team,
       round(100.0 * sum(s.pts) / sum(s.poss), 1)             AS ortg_from_lineups,
       tw.off_rating                                           AS ortg_team_endpoint,
       round(sum(s.poss)::numeric / tw.poss, 3)                AS poss_ratio
FROM lineup_window_stats s
JOIN lineups l USING (lineup_id, season_id)
JOIN teams t USING (team_id)
JOIN team_window_stats tw ON tw.team_id = l.team_id AND tw.season_id = s.season_id AND tw.window_type = s.window_type
WHERE s.season_id = '2023-24' AND s.window_type = 'pre_asb'
GROUP BY t.abbreviation, tw.off_rating, tw.poss
ORDER BY t.abbreviation LIMIT 5;

-- 5) LEFT JOIN to measure selection: of pre-break lineups with >= 50 poss, how many reappear after the break?
--    (Phase 0's selection-bias finding, now reproduced in SQL from the database.)
\echo '--- 5. Do pre-break lineups (>= 50 poss) reappear after the break?'
SELECT pre.season_id,
       count(*)                                         AS pre_lineups,
       -- coalesce is essential: without it, NULL (no post row) > 0 is NULL, and avg() silently SKIPS
       -- NULLs, so non-reappearing lineups would vanish from the denominator (an inflated share).
       round(avg((coalesce(post.poss, 0) > 0)::int), 3) AS share_reappear,
       round(avg((coalesce(post.poss, 0) >= 50)::int), 3) AS share_50plus_post
FROM lineup_window_stats pre
LEFT JOIN lineup_window_stats post ON post.lineup_id = pre.lineup_id AND post.window_type = 'post_asb'
WHERE pre.window_type = 'pre_asb' AND pre.poss >= 50
GROUP BY pre.season_id ORDER BY pre.season_id;

-- 6) Reusable SQL function + aggregate-then-divide: team ratings from lineup totals (Phase 3 view).
\echo '--- 6. Best pre-break team net ratings from lineup totals, 2023-24'
SELECT abbreviation AS team, poss, opp_poss,
       round(off_rating, 1) AS ortg, round(def_rating, 1) AS drtg, round(net_rating, 1) AS net
FROM v_team_window_ratings
WHERE season_id = '2023-24' AND window_type = 'pre_asb'
ORDER BY net_rating DESC LIMIT 5;

-- 7) Player on-court ratings per team (bridge table + aggregation), with a minimum sample.
\echo '--- 7. Top pre-break on-court net ratings, 2023-24 (>= 1500 possessions)'
SELECT p.player_name, t.abbreviation AS team, o.poss, round(o.net_rating, 1) AS on_court_net
FROM v_player_window_on_court o
JOIN players p USING (player_id) JOIN teams t USING (team_id)
WHERE o.season_id = '2023-24' AND o.window_type = 'pre_asb' AND o.poss >= 1500
ORDER BY o.net_rating DESC LIMIT 5;

-- 8) The FILTER clause: why DRtg must restrict numerator and denominator to the same rows.
\echo '--- 8. Rows with unknown opponent possessions (all zero-second appearances), all seasons'
SELECT count(*) AS rows_unknown_opp_poss, sum(opp_pts) AS opp_pts_in_those_rows, sum(seconds) AS seconds
FROM lineup_window_stats WHERE opp_poss IS NULL;

-- 9) Split-half reliability in pure SQL (Phase 4): correlate each lineup's HOME and ROAD net ratings.
--    Disjoint games -> independent sampling errors, so corr() measures signal, not shared noise.
--    Self-join on the split table + corr() aggregate + Spearman-Brown step-up to the full window.
\echo '--- 9. Home vs road net rating, pre-break lineups with >= 50 poss per half (development seasons)'
WITH h AS (SELECT lineup_id, per100(pts, poss) - per100(opp_pts, opp_poss) AS net, poss, opp_poss
           FROM lineup_split_stats WHERE split = 'home'),
     r AS (SELECT lineup_id, per100(pts, poss) - per100(opp_pts, opp_poss) AS net, poss, opp_poss
           FROM lineup_split_stats WHERE split = 'road')
SELECT count(*) AS lineups,
       round(corr(h.net, r.net)::numeric, 3)                                  AS split_half_r,
       round((2 * corr(h.net, r.net) / (1 + corr(h.net, r.net)))::numeric, 3) AS spearman_brown,
       round(avg(h.net - r.net), 2)                                           AS home_minus_road
FROM h JOIN r USING (lineup_id)
WHERE least(h.poss, h.opp_poss, r.poss, r.opp_poss) >= 50;

-- ===================================================================== Phase 5: feature inputs
-- Every feature query reads window_type = 'pre_asb' only: features must exist at the All-Star break.

-- 10) Team prior with leave-lineup-out: team net from all OTHER lineups (window function + subtraction).
--     Removing the lineup's own possessions keeps "team context" and "lineup history" separate.
\echo '--- 10. Team prior excluding the lineup itself, biggest pre-break lineups, 2023-24'
WITH lw AS (SELECT l.season_id, l.team_id, s.lineup_id, s.poss, coalesce(s.opp_poss, 0) AS opp_poss, s.pts,
                   CASE WHEN s.opp_poss IS NULL THEN 0 ELSE s.opp_pts END AS opp_pts
            FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id)
            WHERE s.window_type = 'pre_asb' AND s.season_id = '2023-24'),
     t AS (SELECT *, sum(poss) OVER w AS t_poss, sum(opp_poss) OVER w AS t_opp_poss,
                     sum(pts) OVER w AS t_pts, sum(opp_pts) OVER w AS t_opp_pts
           FROM lw WINDOW w AS (PARTITION BY season_id, team_id))
SELECT tm.abbreviation AS team, t.lineup_id, t.poss,
       round(per100(t.pts, t.poss) - per100(t.opp_pts, t.opp_poss), 1) AS lineup_net,
       round(per100(t_pts - t.pts, t_poss - t.poss) - per100(t_opp_pts - t.opp_pts, t_opp_poss - t.opp_poss), 1)
         AS team_net_without_lineup
FROM t JOIN teams tm USING (team_id)
ORDER BY t.poss DESC LIMIT 5;

-- 11) Player on-off from lineup data (view v_player_window_on_off). Off-court = team total - on-court.
\echo '--- 11. Largest pre-break on-off net ratings, 2023-24 (>= 1500 on-court possessions)'
SELECT p.player_name, tm.abbreviation AS team, o.on_poss, o.off_poss,
       round(o.on_net_rating, 1) AS on_net, round(o.off_net_rating, 1) AS off_net, round(o.on_off_net, 1) AS on_off
FROM v_player_window_on_off o JOIN players p USING (player_id) JOIN teams tm USING (team_id)
WHERE o.season_id = '2023-24' AND o.window_type = 'pre_asb' AND o.on_poss >= 1500
ORDER BY o.on_off_net DESC LIMIT 5;

-- 12) Pair familiarity: possessions two teammates shared before the break (self-join on the bridge table).
\echo '--- 12. Most-used pre-break player pairs, 2023-24'
SELECT tm.abbreviation AS team, pa.player_name AS player_a, pb.player_name AS player_b, sum(s.poss) AS shared_poss
FROM lineup_window_stats s
JOIN lineups l USING (lineup_id, season_id)
JOIN lineup_players a ON a.lineup_id = s.lineup_id
JOIN lineup_players b ON b.lineup_id = s.lineup_id AND a.player_id < b.player_id
JOIN players pa ON pa.player_id = a.player_id JOIN players pb ON pb.player_id = b.player_id
JOIN teams tm ON tm.team_id = l.team_id
WHERE s.window_type = 'pre_asb' AND s.season_id = '2023-24'
GROUP BY tm.abbreviation, pa.player_name, pb.player_name
ORDER BY shared_poss DESC LIMIT 5;

-- 13) The modeling sample and its "no history" share: LEFT JOIN + coalesce (see query 5 for why).
\echo '--- 13. Post-break lineups (>= 25 poss each end) and how many had no pre-break possessions'
SELECT post.season_id, count(*) AS lineups,
       round(avg((coalesce(pre.poss, 0) = 0 OR coalesce(pre.opp_poss, 0) = 0)::int), 3) AS share_no_history,
       round(sum(post.poss) FILTER (WHERE coalesce(pre.poss, 0) = 0 OR coalesce(pre.opp_poss, 0) = 0)::numeric
             / sum(post.poss), 3) AS poss_share_no_history
FROM lineup_window_stats post
LEFT JOIN lineup_window_stats pre ON pre.lineup_id = post.lineup_id AND pre.window_type = 'pre_asb'
WHERE post.window_type = 'post_asb' AND post.poss >= 25 AND post.opp_poss >= 25
  AND post.season_id IN ('2018-19', '2019-20', '2020-21', '2021-22', '2022-23', '2023-24')
GROUP BY post.season_id ORDER BY post.season_id;
