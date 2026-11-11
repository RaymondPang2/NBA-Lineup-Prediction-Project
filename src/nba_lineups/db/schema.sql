-- =====================================================================
-- Silver layer: cleaned, typed, normalized NBA data (PostgreSQL 17).
-- Idempotent: safe to run repeatedly (IF NOT EXISTS / OR REPLACE).
--
-- Every table states its GRAIN, i.e. what exactly one row represents.
-- Derived values (ratings) live in VIEWS, not tables, so they can never
-- drift out of sync with the counts they are computed from.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;  -- lets an EXCLUDE constraint mix '=' and range overlap

-- ---------------------------------------------------------------- dimensions

-- Grain: one NBA regular season.
CREATE TABLE IF NOT EXISTS seasons (
    season_id        TEXT PRIMARY KEY CHECK (season_id ~ '^\d{4}-\d{2}$'),
    start_year       SMALLINT NOT NULL,
    is_irregular     BOOLEAN NOT NULL DEFAULT FALSE,   -- 2019-20 bubble, 2020-21 shortened
    first_game_date  DATE NOT NULL,
    last_game_date   DATE NOT NULL,
    CHECK (first_game_date < last_game_date),
    CHECK (substr(season_id, 1, 4)::int = start_year),
    CHECK (substr(season_id, 6, 2)::int = (start_year + 1) % 100)
);

-- Grain: one date window (pre/post All-Star break) within a season.
CREATE TABLE IF NOT EXISTS stat_windows (
    season_id    TEXT NOT NULL REFERENCES seasons ON DELETE CASCADE,
    window_type  TEXT NOT NULL CHECK (window_type IN ('pre_asb', 'post_asb')),
    date_from    DATE NOT NULL,
    date_to      DATE NOT NULL,
    PRIMARY KEY (season_id, window_type),
    CHECK (date_from <= date_to),
    -- Leakage guard in the database itself: two windows of the same season may never overlap.
    EXCLUDE USING gist (season_id WITH =, daterange(date_from, date_to, '[]') WITH &&)
);

-- Grain: one franchise (team_id is stable across these seasons).
CREATE TABLE IF NOT EXISTS teams (
    team_id       INT PRIMARY KEY,
    abbreviation  TEXT NOT NULL CHECK (abbreviation ~ '^[A-Z]{2,4}$'),
    team_name     TEXT NOT NULL
);

-- Grain: one player.
CREATE TABLE IF NOT EXISTS players (
    player_id    INT PRIMARY KEY CHECK (player_id > 0),
    player_name  TEXT NOT NULL
);

-- Grain: one five-man unit for one team in one season.
-- lineup_id is a surrogate key; (season_id, team_id, player_key) is the natural key.
-- Reloads upsert lineups, so lineup_id stays stable for downstream tables (predictions).
CREATE TABLE IF NOT EXISTS lineups (
    lineup_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    season_id   TEXT NOT NULL REFERENCES seasons ON DELETE CASCADE,
    team_id     INT  NOT NULL REFERENCES teams,
    player_key  TEXT NOT NULL CHECK (player_key ~ '^\d+(-\d+){4}$'),  -- 5 ids, numeric order
    UNIQUE (season_id, team_id, player_key),
    UNIQUE (lineup_id, season_id)  -- target of a composite FK below
);

-- Grain: one player in one lineup (bridge table: resolves the lineup <-> player many-to-many).
CREATE TABLE IF NOT EXISTS lineup_players (
    lineup_id  BIGINT NOT NULL REFERENCES lineups ON DELETE CASCADE,
    player_id  INT    NOT NULL REFERENCES players,
    PRIMARY KEY (lineup_id, player_id)
);
CREATE INDEX IF NOT EXISTS ix_lineup_players_player ON lineup_players (player_id);  -- "lineups containing player X"

-- ---------------------------------------------------------------- facts

-- Grain: one team in one game (from LeagueGameLog). Used to reconcile lineup totals.
CREATE TABLE IF NOT EXISTS team_games (
    game_id     TEXT NOT NULL,
    team_id     INT  NOT NULL REFERENCES teams,
    season_id   TEXT NOT NULL REFERENCES seasons ON DELETE CASCADE,
    game_date   DATE NOT NULL,
    is_home     BOOLEAN,            -- NULL = neutral site (both game-log rows list the team as away '@')
    won         BOOLEAN NOT NULL,
    minutes     SMALLINT NOT NULL CHECK (minutes >= 240),     -- 5 players x 48 min; more with overtime
    pts         SMALLINT NOT NULL CHECK (pts >= 0),
    plus_minus  SMALLINT NOT NULL,
    PRIMARY KEY (game_id, team_id)
);
CREATE INDEX IF NOT EXISTS ix_team_games_season_team ON team_games (season_id, team_id, game_date);
-- Migration (2026-11-10): databases created before neutral-site games were modelled had NOT NULL here.
-- Idempotent: dropping a NOT NULL that is already absent is a no-op.
ALTER TABLE team_games ALTER COLUMN is_home DROP NOT NULL;

-- Grain: one lineup in one window. Additive TOTALS only; ratings are computed in views.
CREATE TABLE IF NOT EXISTS lineup_window_stats (
    lineup_id      BIGINT NOT NULL,
    season_id      TEXT   NOT NULL,
    window_type    TEXT   NOT NULL,
    n_source_rows  SMALLINT NOT NULL DEFAULT 1 CHECK (n_source_rows >= 1),  -- >1: merged name-variant rows
    gp             SMALLINT NOT NULL CHECK (gp >= 0),      -- summed across merged rows (upper bound)
    seconds        NUMERIC(10,1) NOT NULL CHECK (seconds >= 0),  -- SUM_TIME_PLAYED / 50 (exact)
    poss           INT NOT NULL CHECK (poss >= 0),         -- own (offensive) possessions
    opp_poss_implied NUMERIC(9,2) CHECK (opp_poss_implied >= 0),  -- route A (100*OPP_PTS/DEF_RATING), validation only
    opp_poss       INT CHECK (opp_poss >= 0),              -- CANONICAL opponent possessions (exact integer; Phase 3)
    opp_poss_method TEXT CHECK (opp_poss_method IN ('pace', 'def_rating', 'mixed')),
    fgm  INT NOT NULL CHECK (fgm  >= 0), fga  INT NOT NULL CHECK (fga  >= 0),
    fg3m INT NOT NULL CHECK (fg3m >= 0), fg3a INT NOT NULL CHECK (fg3a >= 0),
    ftm  INT NOT NULL CHECK (ftm  >= 0), fta  INT NOT NULL CHECK (fta  >= 0),
    oreb INT NOT NULL CHECK (oreb >= 0), dreb INT NOT NULL CHECK (dreb >= 0),
    ast  INT NOT NULL CHECK (ast  >= 0), tov  INT NOT NULL CHECK (tov  >= 0),
    pts  INT NOT NULL CHECK (pts  >= 0),
    opp_fgm  INT NOT NULL CHECK (opp_fgm  >= 0), opp_fga  INT NOT NULL CHECK (opp_fga  >= 0),
    opp_fg3m INT NOT NULL CHECK (opp_fg3m >= 0), opp_fg3a INT NOT NULL CHECK (opp_fg3a >= 0),
    opp_ftm  INT NOT NULL CHECK (opp_ftm  >= 0), opp_fta  INT NOT NULL CHECK (opp_fta  >= 0),
    opp_oreb INT NOT NULL CHECK (opp_oreb >= 0), opp_dreb INT NOT NULL CHECK (opp_dreb >= 0),
    opp_tov  INT NOT NULL CHECK (opp_tov  >= 0),
    opp_pts  INT NOT NULL CHECK (opp_pts  >= 0),
    plus_minus INT NOT NULL,
    -- NBA's own published ratings, kept for validation. Only meaningful for un-merged rows.
    nba_off_rating NUMERIC(6,1), nba_def_rating NUMERIC(6,1), nba_net_rating NUMERIC(6,1), nba_pace NUMERIC(10,2),  -- pace explodes for few-second lineups (real max > 28,000)
    PRIMARY KEY (lineup_id, window_type),
    -- Composite FKs: the stats row's season must equal its lineup's season AND name a real window.
    FOREIGN KEY (lineup_id, season_id) REFERENCES lineups (lineup_id, season_id) ON DELETE CASCADE,
    FOREIGN KEY (season_id, window_type) REFERENCES stat_windows ON DELETE CASCADE,
    -- Basketball identities (verified to hold on real data in Phase 2):
    CHECK (fgm <= fga AND fg3m <= fg3a AND ftm <= fta AND fg3m <= fgm AND fg3a <= fga),
    CHECK (opp_fgm <= opp_fga AND opp_fg3m <= opp_fg3a AND opp_ftm <= opp_fta AND opp_fg3m <= opp_fgm),
    CHECK (pts = 2 * fgm + fg3m + ftm),
    CHECK (opp_pts = 2 * opp_fgm + opp_fg3m + opp_ftm),
    CHECK (plus_minus = pts - opp_pts),
    CHECK (n_source_rows = 1 OR (nba_off_rating IS NULL AND nba_def_rating IS NULL)),
    CHECK ((opp_poss IS NULL) = (opp_poss_method IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_lws_season_window ON lineup_window_stats (season_id, window_type);
-- Migration (Phase 3): canonical opponent possessions for databases created in Phase 2.
ALTER TABLE lineup_window_stats
    ADD COLUMN IF NOT EXISTS opp_poss INT CHECK (opp_poss >= 0),
    ADD COLUMN IF NOT EXISTS opp_poss_method TEXT CHECK (opp_poss_method IN ('pace', 'def_rating', 'mixed'));

-- Grain: one lineup, one window, one game location (Phase 4). Home and road games are disjoint,
-- interleaved through the season, so the two rows of a lineup are independent half-samples: the
-- basis of the split-half reliability analysis. Only loaded for the pre-break window of development
-- seasons. Home + road reconcile exactly with lineup_window_stats (checked in etl/splits.py).
CREATE TABLE IF NOT EXISTS lineup_split_stats (
    lineup_id      BIGINT NOT NULL,
    season_id      TEXT   NOT NULL,
    window_type    TEXT   NOT NULL,
    split          TEXT   NOT NULL CHECK (split IN ('home', 'road')),
    n_source_rows  SMALLINT NOT NULL CHECK (n_source_rows >= 1),
    gp             SMALLINT NOT NULL CHECK (gp >= 0),
    seconds        NUMERIC(10,1) NOT NULL CHECK (seconds >= 0),
    poss           INT NOT NULL CHECK (poss >= 0),
    opp_poss       INT CHECK (opp_poss >= 0),
    opp_poss_method TEXT CHECK (opp_poss_method IN ('pace', 'def_rating', 'mixed')),
    pts            INT NOT NULL CHECK (pts >= 0),
    opp_pts        INT NOT NULL CHECK (opp_pts >= 0),
    plus_minus     INT NOT NULL,
    nba_off_rating NUMERIC(6,1), nba_def_rating NUMERIC(6,1), nba_net_rating NUMERIC(6,1),
    PRIMARY KEY (lineup_id, window_type, split),
    -- A split row can only exist for a lineup-window that exists in the full-window table.
    FOREIGN KEY (lineup_id, window_type) REFERENCES lineup_window_stats (lineup_id, window_type) ON DELETE CASCADE,
    FOREIGN KEY (lineup_id, season_id) REFERENCES lineups (lineup_id, season_id) ON DELETE CASCADE,
    CHECK (plus_minus = pts - opp_pts),
    CHECK ((opp_poss IS NULL) = (opp_poss_method IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_lss_season ON lineup_split_stats (season_id, window_type);

-- Grain: one player in one window. NOTE: the API combines a traded player's teams into one row,
-- labelled with the latest team, so per-team player features must come from lineup data.
CREATE TABLE IF NOT EXISTS player_window_stats (
    player_id    INT  NOT NULL REFERENCES players,
    season_id    TEXT NOT NULL,
    window_type  TEXT NOT NULL,
    -- LEAKAGE WARNING (Phase 4): the API fills TEAM_ID with the player's LATEST team even under a date
    -- filter, so a pre_asb row can name a team the player only joined after the break (e.g. Vucevic
    -- 2020-21: every pre-break game for ORL, row says CHI). Never use it as a feature; derive teams
    -- from lineup data (v_player_window_on_court). NULL if the API reports team 0.
    last_team_id INT  REFERENCES teams,
    gp           SMALLINT NOT NULL CHECK (gp >= 0),
    minutes      NUMERIC(8,2) NOT NULL CHECK (minutes >= 0),
    poss         INT NOT NULL CHECK (poss >= 0),
    off_rating   NUMERIC(6,1), def_rating NUMERIC(6,1), net_rating NUMERIC(6,1),
    usg_pct      NUMERIC(5,3), ts_pct NUMERIC(5,3),
    PRIMARY KEY (player_id, season_id, window_type),
    FOREIGN KEY (season_id, window_type) REFERENCES stat_windows ON DELETE CASCADE
);

-- Grain: one team in one window (team endpoint). Its POSS uses a different possession count from
-- the lineup feed (lineup sum is ~3-4% higher), so features use lineup-derived team totals instead.
CREATE TABLE IF NOT EXISTS team_window_stats (
    team_id      INT  NOT NULL REFERENCES teams,
    season_id    TEXT NOT NULL,
    window_type  TEXT NOT NULL,
    gp           SMALLINT NOT NULL CHECK (gp > 0),
    minutes      NUMERIC(8,1) NOT NULL CHECK (minutes > 0),
    poss         INT NOT NULL CHECK (poss > 0),
    off_rating   NUMERIC(6,1) NOT NULL, def_rating NUMERIC(6,1) NOT NULL, net_rating NUMERIC(6,1) NOT NULL,
    pace         NUMERIC(6,2) NOT NULL,
    PRIMARY KEY (team_id, season_id, window_type),
    FOREIGN KEY (season_id, window_type) REFERENCES stat_windows ON DELETE CASCADE
);

-- ---------------------------------------------------------------- lineage / audit

-- Grain: one fetch outcome from data/ingestion_log.jsonl (append-only).
CREATE TABLE IF NOT EXISTS ingestion_log (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       TEXT NOT NULL,
    request_key  TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    season_id    TEXT NOT NULL,          -- no FK: the log may mention seasons not (yet) loaded
    window_type  TEXT,
    measure      TEXT,
    team_id      INT,
    params       JSONB NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('success', 'failed', 'invalid')),
    attempts     SMALLINT NOT NULL CHECK (attempts >= 1),
    duration_s   NUMERIC(8,3) NOT NULL,
    row_count    INT,
    raw_path     TEXT,
    sha256       CHAR(64),
    errors       JSONB NOT NULL DEFAULT '[]',
    warnings     JSONB NOT NULL DEFAULT '[]',
    recorded_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, request_key, recorded_at)   -- makes re-loading the log idempotent
);

-- Grain: one ETL (bronze -> silver) run.
CREATE TABLE IF NOT EXISTS etl_runs (
    etl_run_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    seasons      TEXT[] NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
    row_counts   JSONB,
    dq_results   JSONB,
    error        TEXT
);

-- ---------------------------------------------------------------- views (derived, never stored)

-- per100: the single SQL definition of a per-100-possession rate (mirrors nba_lineups.metrics.per100).
-- NULL (undefined) when possessions are 0 or unknown. NBA's API reports 0.0 there, which would bias averages.
-- IMMUTABLE lets the planner inline and cache it; it has no side effects.
CREATE OR REPLACE FUNCTION per100(num NUMERIC, poss NUMERIC) RETURNS NUMERIC
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    RETURN CASE WHEN poss > 0 THEN 100.0 * num / poss END;

-- Views are dropped and recreated because CREATE OR REPLACE VIEW cannot remove or rename columns.
DROP VIEW IF EXISTS v_player_window_on_court, v_team_window_ratings, v_lineup_season_ratings,
                    v_lineup_window_ratings CASCADE;

-- Grain: one lineup in one window. Ratings are EXACT (unrounded); round only for display.
-- Contract: ORtg = per100(pts, OWN poss); DRtg = per100(opp_pts, OPPONENT poss).
CREATE VIEW v_lineup_window_ratings AS
SELECT s.lineup_id, l.season_id, l.team_id, t.abbreviation, l.player_key, s.window_type,
       s.n_source_rows, s.gp, s.seconds / 60.0 AS minutes,
       s.poss, s.opp_poss, s.opp_poss_method, s.pts, s.opp_pts, s.plus_minus,
       per100(s.pts, s.poss)                                    AS off_rating,
       per100(s.opp_pts, s.opp_poss)                            AS def_rating,
       per100(s.pts, s.poss) - per100(s.opp_pts, s.opp_poss)    AS net_rating,
       CASE WHEN s.seconds > 0 THEN 48 * (s.poss + s.opp_poss) / 2.0 / (s.seconds / 60.0) END AS pace,
       s.nba_off_rating, s.nba_def_rating, s.nba_net_rating
FROM lineup_window_stats s
JOIN lineups l USING (lineup_id, season_id)
JOIN teams   t USING (team_id);

-- AGGREGATE-THEN-DIVIDE pattern used by every aggregated view below:
--   off: per100(sum(pts), sum(poss))
--   def: per100(sum(opp_pts) FILTER (WHERE opp_poss IS NOT NULL), sum(opp_poss))
-- SUM() silently skips NULLs, so a row with unknown opp_poss would otherwise add its points to the
-- numerator but nothing to the denominator (an inflated DRtg). FILTER keeps numerator and denominator
-- on the same rows. Unknown opp_poss occurs only for zero-second rows (see docs/metrics.md).

-- Grain: one lineup in one season (both windows combined).
CREATE VIEW v_lineup_season_ratings AS
SELECT l.lineup_id, l.season_id, l.team_id, l.player_key,
       sum(s.seconds) / 60.0 AS minutes, sum(s.poss) AS poss, sum(s.opp_poss) AS opp_poss,
       sum(s.pts) AS pts, sum(s.opp_pts) AS opp_pts,
       per100(sum(s.pts), sum(s.poss)) AS off_rating,
       per100(sum(s.opp_pts) FILTER (WHERE s.opp_poss IS NOT NULL), sum(s.opp_poss)) AS def_rating,
       per100(sum(s.pts), sum(s.poss))
         - per100(sum(s.opp_pts) FILTER (WHERE s.opp_poss IS NOT NULL), sum(s.opp_poss)) AS net_rating
FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id)
GROUP BY l.lineup_id, l.season_id, l.team_id, l.player_key;

-- Grain: one team in one window, built from LINEUP totals (same possession definition as lineups;
-- the team endpoint counts ~3-4% fewer possessions, see docs/database.md).
CREATE VIEW v_team_window_ratings AS
SELECT l.season_id, s.window_type, l.team_id, t.abbreviation,
       sum(s.seconds) / 60.0 AS lineup_minutes, sum(s.poss) AS poss, sum(s.opp_poss) AS opp_poss,
       sum(s.pts) AS pts, sum(s.opp_pts) AS opp_pts,
       per100(sum(s.pts), sum(s.poss)) AS off_rating,
       per100(sum(s.opp_pts) FILTER (WHERE s.opp_poss IS NOT NULL), sum(s.opp_poss)) AS def_rating,
       per100(sum(s.pts), sum(s.poss))
         - per100(sum(s.opp_pts) FILTER (WHERE s.opp_poss IS NOT NULL), sum(s.opp_poss)) AS net_rating
FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id) JOIN teams t USING (team_id)
GROUP BY l.season_id, s.window_type, l.team_id, t.abbreviation;

-- Grain: one player, for one team, in one window: on-court totals pooled over every lineup they were in.
-- (Per team, unlike the player endpoint, which merges a traded player's teams.)
CREATE VIEW v_player_window_on_court AS
SELECT l.season_id, s.window_type, l.team_id, lp.player_id,
       count(*) AS n_lineups, sum(s.seconds) / 60.0 AS minutes,
       sum(s.poss) AS poss, sum(s.opp_poss) AS opp_poss, sum(s.pts) AS pts, sum(s.opp_pts) AS opp_pts,
       per100(sum(s.pts), sum(s.poss)) AS off_rating,
       per100(sum(s.opp_pts) FILTER (WHERE s.opp_poss IS NOT NULL), sum(s.opp_poss)) AS def_rating,
       per100(sum(s.pts), sum(s.poss))
         - per100(sum(s.opp_pts) FILTER (WHERE s.opp_poss IS NOT NULL), sum(s.opp_poss)) AS net_rating
FROM lineup_window_stats s
JOIN lineups l USING (lineup_id, season_id)
JOIN lineup_players lp USING (lineup_id)
GROUP BY l.season_id, s.window_type, l.team_id, lp.player_id;
