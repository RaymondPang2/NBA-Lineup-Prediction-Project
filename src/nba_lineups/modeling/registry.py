"""Feature dictionary: the single source for documentation, the CSV dictionary and the column-contract tests.

Every feature is computed from pre-break data only, so every feature is AVAILABLE AT the end of the last
pre-break game day (`stat_windows.date_to` of the season's `pre_asb` window). Fitted parameters are learned
on the training seasons of each fold (FeatureBuilder.fit).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

AVAILABLE_AT = "End of the last pre-break game day (stat_windows.date_to, window pre_asb)"
FIVE = "mean over the lineup's five players"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str          # team | player | lineup
    description: str
    source: str         # tables / views the raw inputs come from
    fitted: str         # what is learned on training folds ("none": deterministic)
    no_history: str     # value when the underlying data doesn't exist


_LW = "lineup_window_stats (pre_asb) + lineups"
_PT = "lineup_window_stats (pre_asb) + lineup_players → on/off-court totals (same as v_player_window_on_off)"
_EB_PLAYER = "EB prior mean β0 + β1·log(poss), τ², K (training players with ≥ 10 poss)"

FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("team_off_rating_loo", "team",
                "Team pre-break ORtg from all OTHER lineups of the team (100·Σpts/Σposs)", _LW, "none",
                "never missing (every team plays before the break)"),
    FeatureSpec("team_def_rating_loo", "team",
                "Team pre-break DRtg from all OTHER lineups (100·Σopp_pts/Σopp_poss)", _LW, "none",
                "never missing"),
    FeatureSpec("p_off_rating_eb_mean", "player",
                f"EB-shrunk on-court ORtg (all pre-break teams pooled), {FIVE}", _PT, _EB_PLAYER,
                "prior of a 10-possession player"),
    FeatureSpec("p_def_rating_eb_mean", "player",
                f"EB-shrunk on-court DRtg, {FIVE}", _PT, _EB_PLAYER, "prior of a 10-possession player"),
    FeatureSpec("p_net_rating_eb_mean", "player",
                f"EB-shrunk on-court net rating, {FIVE}", _PT, _EB_PLAYER, "prior of a 10-possession player"),
    FeatureSpec("p_on_off_eb_mean", "player",
                f"EB-shrunk on-off net (on-court net − off-court net of the same teams), {FIVE}", _PT,
                _EB_PLAYER, "prior of a 10-possession player"),
    FeatureSpec("p_usage_eb_mean", "player",
                f"EB-shrunk usage % (player endpoint, pre-break; team label never used), {FIVE}",
                "player_window_stats.usg_pct, poss (pre_asb)", "EB prior β0 + β1·log(poss), τ², K",
                "prior of a 10-possession player"),
    FeatureSpec("p_usage_eb_max", "player", "Highest EB-shrunk usage % among the five",
                "player_window_stats (pre_asb)", "as p_usage_eb_mean", "as p_usage_eb_mean"),
    FeatureSpec("p_log_poss_mean", "player",
                f"log(1 + pre-break on-court possessions, all teams), {FIVE}: role / experience", _PT, "none",
                "0"),
    FeatureSpec("p_team_share_min", "player",
                "Least-used player's share of THIS team's pre-break possessions (rotation depth)", _PT, "none",
                "0 (player had no pre-break possessions for this team)"),
    FeatureSpec("p_n_new_to_team", "player",
                "Players with no pre-break possessions for this team (deadline trades, returns from injury)", _PT,
                "none", "counts them"),
    FeatureSpec("p_n_no_history", "player",
                "Players with no pre-break possessions for ANY team (subset of p_n_new_to_team)", _PT, "none",
                "counts them"),
    FeatureSpec("lu_log_poss", "lineup", "log(1 + the lineup's own pre-break possessions)", _LW, "none", "0"),
    FeatureSpec("lu_no_history", "lineup",
                "1 if the lineup has no pre-break possessions on offense or defense (rating undefined)", _LW,
                "none", "1"),
    FeatureSpec("lu_net_eb_team", "lineup",
                "Lineup's pre-break net rating, EB-shrunk toward the team prior (team_net_loo + μ)", _LW,
                "EB μ, τ², K (training lineups with ≥ 10 poss each end)", "the team prior"),
    FeatureSpec("lu_pair_familiarity", "lineup",
                "Mean over the 10 player pairs of log(1 + pre-break possessions the pair shared for this team)",
                "lineup_window_stats (pre_asb) + lineup_players (pairs)", "none", "0 for a pair that never shared the floor"),
)
FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in FEATURES)

# Columns the builder also returns for baselines and diagnostics. They aren't model features.
AUXILIARY = {
    "team_net_loo": "Team pre-break net rating from all other lineups (the team prior)",
    "lu_poss": "Lineup's own pre-break possessions", "lu_opp_poss": "Lineup's own pre-break opponent possessions",
    "lu_net_raw": "Lineup's raw pre-break net rating (NaN without history)",
    "lu_reliability": "Shrinkage factor B = τ²/(τ² + K·h) of the lineup's history (0 without history)",
}


def dictionary() -> pd.DataFrame:
    df = pd.DataFrame([asdict(f) for f in FEATURES])
    df["window"] = "pre_asb"
    df["available_at"] = AVAILABLE_AT
    return df
