"""Stage 1: deterministic pre-break aggregates (no learned parameters).

Everything here is a sum of one season's PRE-BREAK totals, so it's available at the All-Star break
(prediction time) and can be computed once without leaking information between folds.

Leakage contract:
- Feature tables are read from `window_type = 'pre_asb'` rows only. `PreBreakTables.validate` re-checks it.
- Teams come from the LINEUP feed (each lineup was requested per team). `player_window_stats.last_team_id`
  is never selected: the API fills it with the player's latest team even under a pre-break date filter.
- Only development seasons can be requested (`access.check_seasons`). Held-out seasons raise HeldOutDataError
  unless a HoldoutKey is passed, which only `holdout.unlock` can issue once the final model is frozen.
- `load_targets` is the only function that reads post-break data, and it returns labels, never features.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import psycopg

from ..analysis.data import HeldOutDataError, query  # noqa: F401  (re-exported for callers and tests)
from ..config import DEV_SEASONS, IRREGULAR_SEASONS
from .access import HoldoutKey, check_seasons, require_allowed

PRE = "pre_asb"
MIN_TARGET_POSS = 25   # target sample: >= 25 post-break possessions on EACH end (approved design)
TOTALS = ["poss", "opp_poss", "pts", "opp_pts"]


class LeakageError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreBreakTables:
    """Pre-break inputs for a set of seasons. All later features are computed from these frames."""
    lineups: pd.DataFrame       # one row per pre-break lineup-window: season_id, team_id, lineup_id, window_type, gp, poss, opp_poss, pts, opp_pts
    members: pd.DataFrame       # lineup_id, season_id, team_id, player_id: composition of ANY lineup (the query, not a statistic)
    usage: pd.DataFrame         # season_id, player_id, window_type, usage_poss, usg_pct (player endpoint, pre-break; no team label)
    player_team: pd.DataFrame   # season_id, team_id, player_id: on-court and off-court totals for that team (derived)
    pairs: pd.DataFrame         # season_id, team_id, player_a, player_b, shared_poss (derived)
    key: HoldoutKey | None = None   # set only for the final held-out evaluation (see access.py)

    @property
    def seasons(self) -> list[str]:
        return sorted(self.lineups.season_id.unique())

    def validate(self) -> PreBreakTables:
        for name in ("lineups", "usage"):
            df = getattr(self, name)
            if (df.window_type != PRE).any():
                raise LeakageError(f"{name} contains post-break rows")
        for name in ("lineups", "members", "usage", "player_team", "pairs"):
            df = getattr(self, name)
            if "last_team_id" in df.columns:
                raise LeakageError("last_team_id leaks post-break trades (the API ignores the date filter for it)")
            require_allowed(df, self.key)
        return self

    def subset(self, seasons: Iterable[str]) -> PreBreakTables:
        s = set(seasons)
        return PreBreakTables(*(getattr(self, f).loc[lambda d: d.season_id.isin(s)].reset_index(drop=True)
                                for f in ("lineups", "members", "usage", "player_team", "pairs")), key=self.key)


def derive_player_team(lineups: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """On-court totals per (season, team, player) pooled over the player's lineups, and OFF-court totals
    (team total minus on-court). Aggregate, then divide: ratings are computed later from these sums."""
    keys = ["season_id", "team_id"]
    team = lineups.groupby(keys)[TOTALS].sum()
    on = (lineups[keys + ["lineup_id"] + TOTALS]
          .merge(members[["lineup_id", "player_id"]], on="lineup_id")
          .groupby(keys + ["player_id"])[TOTALS].sum())
    out = on.add_prefix("on_").reset_index().merge(team.add_prefix("team_").reset_index(), on=keys)
    for c in TOTALS:
        out[f"off_{c}"] = out[f"team_{c}"] - out[f"on_{c}"]
    return out


def lineup_pairs(members: pd.DataFrame) -> pd.DataFrame:
    """The 10 player pairs of each lineup (player_a < player_b)."""
    m = members[["lineup_id", "player_id"]]
    p = m.merge(m, on="lineup_id", suffixes=("_a", "_b"))
    return (p[p.player_id_a < p.player_id_b]
            .rename(columns={"player_id_a": "player_a", "player_id_b": "player_b"}).reset_index(drop=True))


def derive_pairs(lineups: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """Pre-break possessions each pair of teammates shared on court (summed over every lineup with both)."""
    p = lineup_pairs(members[members.lineup_id.isin(lineups.lineup_id)])
    p = p.merge(lineups[["lineup_id", "season_id", "team_id", "poss"]], on="lineup_id")
    return (p.groupby(["season_id", "team_id", "player_a", "player_b"], as_index=False).poss.sum()
            .rename(columns={"poss": "shared_poss"}))


def build_tables(lineups: pd.DataFrame, members: pd.DataFrame, usage: pd.DataFrame,
                 key: HoldoutKey | None = None) -> PreBreakTables:
    return PreBreakTables(lineups, members, usage, derive_player_team(lineups, members),
                          derive_pairs(lineups, members), key=key).validate()


def load_pre_break_tables(conn: psycopg.Connection, seasons: Iterable[str] = DEV_SEASONS,
                          key: HoldoutKey | None = None) -> PreBreakTables:
    """Read the pre-break inputs. Unknown opponent possessions (zero-second rows only) count as 0
    possessions AND 0 points, so numerator and denominator always cover the same rows."""
    p = {"seasons": check_seasons(seasons, key)}
    lineups = query(conn, """
        SELECT l.season_id, l.team_id, s.lineup_id, s.window_type, s.gp, s.poss,
               coalesce(s.opp_poss, 0) AS opp_poss, s.pts,
               CASE WHEN s.opp_poss IS NULL THEN 0 ELSE s.opp_pts END AS opp_pts
        FROM lineup_window_stats s JOIN lineups l USING (lineup_id, season_id)
        WHERE s.window_type = 'pre_asb' AND s.season_id = ANY(%(seasons)s)""", p)
    members = query(conn, """
        SELECT l.lineup_id, l.season_id, l.team_id, lp.player_id
        FROM lineups l JOIN lineup_players lp USING (lineup_id)
        WHERE l.season_id = ANY(%(seasons)s)""", p)
    usage = query(conn, """
        SELECT season_id, player_id, window_type, poss AS usage_poss, usg_pct::float AS usg_pct
        FROM player_window_stats
        WHERE window_type = 'pre_asb' AND season_id = ANY(%(seasons)s)""", p)
    return build_tables(lineups, members, usage, key)


def load_targets(conn: psycopg.Connection, seasons: Iterable[str] = DEV_SEASONS,
                 min_poss: int = MIN_TARGET_POSS, key: HoldoutKey | None = None) -> pd.DataFrame:
    """LABELS: post-break net rating of every lineup with >= min_poss possessions on each end after the break.

    This defines the modeling SAMPLE (the estimand is conditional on the lineup being played after the
    break) and the target. Nothing returned here may become a feature.
    """
    df = require_allowed(query(conn, """
        SELECT season_id, team_id, lineup_id, poss AS post_poss, opp_poss AS post_opp_poss,
               pts AS post_pts, opp_pts AS post_opp_pts, net_rating::float AS y
        FROM v_lineup_window_ratings
        WHERE window_type = 'post_asb' AND season_id = ANY(%(seasons)s)
          AND poss >= %(min_poss)s AND opp_poss >= %(min_poss)s
        ORDER BY season_id, team_id, lineup_id""", {"seasons": check_seasons(seasons, key), "min_poss": min_poss}), key)
    df["w"] = df.post_poss.astype(float)   # possession weight (approved design)
    df["is_irregular"] = df.season_id.isin(IRREGULAR_SEASONS)
    assert np.isfinite(df.y).all()
    return df
