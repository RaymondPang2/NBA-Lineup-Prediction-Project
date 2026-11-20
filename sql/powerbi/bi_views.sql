-- Phase 9: star schema for Power BI, as views in a separate `bi` schema over the validated silver layer.
--
--   docker exec -i nba_lineups_db psql -U nba -d nba_lineups -v ON_ERROR_STOP=1 < sql/powerbi/bi_views.sql
--   (or: .venv/bin/python scripts/phase9/export_powerbi.py, which applies this file first)
--
-- Idempotent: drops and recreates only objects in schema `bi`; the silver tables are read, never written.
-- Grain and keys
--   dim_season           one row per season                     key season_id
--   dim_team             one row per team                       key team_id
--   dim_player           one row per player                     key player_id
--   dim_window           pre_asb / post_asb                     key window_type
--   dim_lineup           one row per lineup (season+team+five)  key lineup_id
--   bridge_lineup_player one row per lineup x player (5 per lineup)
--   fact_lineup_window   one row per lineup x window            keys lineup_id, window_type
--   fact_team_window     one row per team x season x window     (games, wins, losses)
-- Ratings are NOT stored in the facts: Power BI computes them as SUM(points) / SUM(possessions) * 100
-- (aggregate first, then divide). The facts carry additive totals only.
-- fact_prediction (frozen-model output) and model_parameters are produced in Python (export_powerbi.py),
-- because the model lives in Python; they are never written back to the database.

CREATE SCHEMA IF NOT EXISTS bi;

DROP VIEW IF EXISTS bi.fact_team_window, bi.fact_lineup_window, bi.bridge_lineup_player, bi.dim_lineup,
                    bi.dim_window, bi.dim_player, bi.dim_team, bi.dim_season CASCADE;

CREATE VIEW bi.dim_season AS
SELECT s.season_id,
       s.start_year,
       s.is_irregular::int                                                  AS is_irregular,
       -- Held-out seasons (never used for training or tuning); must equal nba_lineups.config.HELDOUT_SEASONS
       CASE WHEN s.season_id IN ('2024-25', '2025-26') THEN 'Held-out' ELSE 'Development' END AS season_role,
       pre.date_from  AS pre_break_from,  pre.date_to  AS pre_break_to,
       post.date_from AS post_break_from, post.date_to AS post_break_to,
       row_number() OVER (ORDER BY s.start_year)::int                       AS season_order
FROM seasons s
JOIN stat_windows pre  ON pre.season_id  = s.season_id AND pre.window_type  = 'pre_asb'
JOIN stat_windows post ON post.season_id = s.season_id AND post.window_type = 'post_asb';

CREATE VIEW bi.dim_team AS
SELECT team_id, abbreviation, team_name FROM teams;

CREATE VIEW bi.dim_player AS
SELECT p.player_id, p.player_name
FROM players p
WHERE EXISTS (SELECT 1 FROM lineup_players lp WHERE lp.player_id = p.player_id);

CREATE VIEW bi.dim_window AS
SELECT * FROM (VALUES ('pre_asb', 'Pre-break', 1), ('post_asb', 'Post-break', 2)) v(window_type, window_label, window_order);

CREATE VIEW bi.dim_lineup AS
WITH names AS (
    SELECT lp.lineup_id,
           -- "Last name" keeps suffixes: Jaren Jackson Jr. -> "Jackson Jr."
           string_agg((regexp_match(p.player_name, '(\S+(?:\s+(?:Jr\.?|Sr\.?|II|III|IV|V))?)$'))[1], ' · '
                      ORDER BY p.player_name)                               AS lineup_label,
           string_agg(p.player_name, ', ' ORDER BY p.player_name)           AS lineup_players
    FROM lineup_players lp JOIN players p USING (player_id)
    GROUP BY lp.lineup_id),
w AS (
    SELECT lineup_id,
           coalesce(sum(poss)                  FILTER (WHERE window_type = 'pre_asb'), 0)  AS pre_poss,
           coalesce(sum(coalesce(opp_poss, 0)) FILTER (WHERE window_type = 'pre_asb'), 0)  AS pre_opp_poss,
           coalesce(sum(poss)                  FILTER (WHERE window_type = 'post_asb'), 0) AS post_poss,
           coalesce(sum(coalesce(opp_poss, 0)) FILTER (WHERE window_type = 'post_asb'), 0) AS post_opp_poss,
           coalesce(sum(seconds) / 60.0, 0)                                                AS season_minutes
    FROM lineup_window_stats GROUP BY lineup_id)
SELECT l.lineup_id, l.season_id, l.team_id, l.player_key,
       n.lineup_label, n.lineup_players,
       w.pre_poss::int, w.pre_opp_poss::int, w.post_poss::int, w.post_opp_poss::int,
       w.season_minutes::float8                                             AS season_minutes,
       -- Pre-break sample size (smaller end), for slicing by reliability
       CASE WHEN least(w.pre_poss, w.pre_opp_poss) = 0   THEN '0 (no pre-break history)'
            WHEN least(w.pre_poss, w.pre_opp_poss) < 25  THEN '1-24'
            WHEN least(w.pre_poss, w.pre_opp_poss) < 100 THEN '25-99'
            WHEN least(w.pre_poss, w.pre_opp_poss) < 300 THEN '100-299'
            ELSE '300+' END                                                 AS pre_sample_tier,
       CASE WHEN least(w.pre_poss, w.pre_opp_poss) = 0   THEN 0
            WHEN least(w.pre_poss, w.pre_opp_poss) < 25  THEN 1
            WHEN least(w.pre_poss, w.pre_opp_poss) < 100 THEN 2
            WHEN least(w.pre_poss, w.pre_opp_poss) < 300 THEN 3
            ELSE 4 END                                                      AS pre_sample_tier_order,
       -- Selection analysis (Phase 4 definitions): population = >= 25 pre-break possessions on each end;
       -- appears = any post-break possession; continues = >= 25 post-break (own) possessions.
       (w.pre_poss >= 25 AND w.pre_opp_poss >= 25)::int                     AS in_continuation_population,
       (w.post_poss > 0)::int                                               AS appears_post_break,
       (w.post_poss >= 25)::int                                             AS continues_post_break,
       CASE WHEN w.pre_poss < 25  THEN NULL
            WHEN w.pre_poss < 50  THEN '[25, 50)'
            WHEN w.pre_poss < 100 THEN '[50, 100)'
            WHEN w.pre_poss < 200 THEN '[100, 200)'
            WHEN w.pre_poss < 400 THEN '[200, 400)'
            ELSE '[400, +)' END                                             AS pre_poss_bin,
       CASE WHEN w.pre_poss < 25  THEN NULL
            WHEN w.pre_poss < 50  THEN 1 WHEN w.pre_poss < 100 THEN 2
            WHEN w.pre_poss < 200 THEN 3 WHEN w.pre_poss < 400 THEN 4 ELSE 5 END AS pre_poss_bin_order,
       -- The model's target sample: >= 25 post-break possessions on EACH end
       (w.post_poss >= 25 AND w.post_opp_poss >= 25)::int                   AS in_target_sample
FROM lineups l
JOIN names n USING (lineup_id)
JOIN w USING (lineup_id);

CREATE VIEW bi.bridge_lineup_player AS
SELECT lineup_id, player_id FROM lineup_players;

CREATE VIEW bi.fact_lineup_window AS
SELECT s.lineup_id, s.season_id, l.team_id, s.window_type,
       s.gp,
       (s.seconds / 60.0)::float8                                AS minutes,   -- unrounded: totals must sum exactly
       s.poss,
       coalesce(s.opp_poss, 0)                                   AS opp_poss,
       s.pts,
       s.opp_pts,
       -- DRtg numerator: opponent points only where opponent possessions are known (same rule as
       -- v_lineup_window_ratings: 162 tiny lineup-windows have no opp_poss)
       CASE WHEN s.opp_poss IS NULL THEN 0 ELSE s.opp_pts END    AS opp_pts_rated,
       s.plus_minus
FROM lineup_window_stats s
JOIN lineups l USING (lineup_id, season_id);

CREATE VIEW bi.fact_team_window AS
SELECT g.season_id, g.team_id, w.window_type,
       count(*)::int                          AS games,
       count(*) FILTER (WHERE g.won)::int     AS wins,
       count(*) FILTER (WHERE NOT g.won)::int AS losses
FROM team_games g
JOIN stat_windows w ON w.season_id = g.season_id AND g.game_date BETWEEN w.date_from AND w.date_to
GROUP BY g.season_id, g.team_id, w.window_type;
