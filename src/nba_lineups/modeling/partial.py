"""Partial pre-break windows (the season in progress): how far along the season is, and a DIAGNOSTIC of how the
frozen model's inputs behave when the pre-break window is incomplete.

Nothing here changes what the API serves. The frozen model and its feature definitions are used exactly as frozen;
the counterfactual below exists only to MEASURE the bias of applying them to a partial window
(docs/partial_window_audit.md). Its output is never shown as a prediction.

Why a partial window shifts the inputs (feature-by-feature audit, model features only):
* rates (team ORtg/DRtg from other lineups, least-used player's team share): unbiased, but noisier early;
* `lu_log_poss`: log of the lineup's possessions, smaller early (coefficient −0.50 per log unit);
* `p_n_no_history`, `p_n_new_to_team`: players without possessions YET (injured to date) count as "no history";
* EB player rates (`p_def_rating_eb_mean`, `p_on_off_eb_mean`, `p_usage_eb_*`): shrunk toward a prior whose
  mean rises with log(possessions) (coaches give better players more minutes). Early in a season every player
  has fewer possessions, so starters get a weaker-player prior and, with thin data, are shrunk hard toward it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import psycopg

from ..config import ALL_SEASONS, IRREGULAR_SEASONS
from . import raw


@dataclass(frozen=True)
class SeasonProgress:
    season_id: str
    team_games_mean: float            # pre-break games per team so far
    typical_full_window: float | None  # mean pre-break games per team in completed regular seasons (None: none loaded)
    per_team_games: dict[int, int]

    @property
    def fraction(self) -> float | None:
        if not self.typical_full_window:
            return None
        return min(1.0, self.team_games_mean / self.typical_full_window)


def season_progress(conn: psycopg.Connection, season: str) -> SeasonProgress:
    rows = conn.execute("""
        SELECT g.season_id, g.team_id, count(*) AS n
        FROM team_games g JOIN stat_windows w ON w.season_id = g.season_id AND w.window_type = 'pre_asb'
             AND g.game_date BETWEEN w.date_from AND w.date_to
        WHERE g.season_id = ANY(%s) GROUP BY 1, 2""",
        (list(ALL_SEASONS) + [season],)).fetchall()
    df = pd.DataFrame(rows, columns=["season_id", "team_id", "n"])
    regular = [s for s in ALL_SEASONS if s not in IRREGULAR_SEASONS and s != season]
    per_season = df[df.season_id.isin(regular)].groupby("season_id").n.mean()
    typical = float(per_season.mean()) if len(per_season) else None
    cur = df[df.season_id == season]
    return SeasonProgress(season, float(cur.n.mean()) if len(cur) else 0.0, typical,
                          {int(t): int(n) for t, n in zip(cur.team_id, cur.n)})


def scaled_tables(t: raw.PreBreakTables, factor_by_team: dict[int, float]) -> raw.PreBreakTables:
    """DIAGNOSTIC counterfactual: every possession/point total multiplied by its team's factor (rates unchanged),
    i.e. 'the same rates observed over a full pre-break window'. Used only to measure volume sensitivity."""
    lu = t.lineups.copy()
    f = lu.team_id.map(factor_by_team).fillna(1.0)
    for c in raw.TOTALS:
        lu[c] = lu[c] * f
    # usage has no team label (by design); scale it by the factor of the player's lineups' team(s)
    pf = (t.members.assign(f=t.members.team_id.map(factor_by_team).fillna(1.0))
          .groupby(["season_id", "player_id"]).f.mean())
    us = t.usage.copy()
    us["usage_poss"] = us.usage_poss * us.set_index(["season_id", "player_id"]).index.map(pf).fillna(1.0).to_numpy()
    return raw.build_tables(lu, t.members, us, key=t.key)


def volume_sensitivity(actual: pd.Series, counterfactual: pd.Series, team: pd.Series) -> dict:
    """How much the served (partial-window) predictions differ from the full-window counterfactual."""
    d = (counterfactual - actual).dropna()
    both = pd.DataFrame({"a": actual, "c": counterfactual, "team": team}).dropna()
    within = [g.a.rank().corr(g.c.rank()) for _, g in both.groupby("team") if len(g) >= 5]
    top_a = set(both.a.nlargest(25).index)
    top_c = set(both.c.nlargest(25).index)
    return {"n": int(len(d)), "mean_shift": float(d.mean()), "sd_shift": float(d.std()),
            "p10_shift": float(np.percentile(d, 10)), "p90_shift": float(np.percentile(d, 90)),
            "spearman_league": float(both.a.rank().corr(both.c.rank())),
            "spearman_within_team_median": float(np.median(within)) if within else None,
            "top25_overlap": len(top_a & top_c)}
