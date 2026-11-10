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
