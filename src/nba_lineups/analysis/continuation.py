"""Which pre-break lineups keep playing after the All-Star break? (selection model)

Unit: a lineup with >= MIN_PRE_POSS possessions before the break (development seasons).
Label: CONTINUES = the lineup plays >= MIN_POST_POSS possessions after the break, i.e. it enters
the Phase 5/6 modeling sample. (`appears` = any post-break possession is reported as well.)

Every feature comes from the pre-break window. `build_features` refuses post-break rows, and
the label is computed by a separate function, so it can never become a feature. This mirrors the
analytical contract: "appears after the break" defines the SAMPLE and is never a feature.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import reliability as rel
from .data import require_dev

MIN_PRE_POSS = 25
MIN_POST_POSS = 25
FEATURES = ["log_poss", "eb_net", "team_net", "min_player_share", "has_traded_player"]
FEATURE_LABELS = {
    "log_poss": "Pre-break possessions (log)",
    "eb_net": "Pre-break net rating (EB-shrunk)",
    "team_net": "Team pre-break net rating",
    "min_player_share": "Least-used player's share of team possessions",
    "has_traded_player": "Includes a player who played for 2+ teams pre-break",
}


class LeakageError(RuntimeError):
    pass


def eb_net_rating(pre: pd.DataFrame, vc: rel.VarianceComponents) -> pd.Series:
    """EB-shrunk pre-break net rating toward the league mean (hyperparameters passed in, never refit here)."""
    h = rel.sampling_h(pre.poss, pre.opp_poss)
    post, _ = rel.shrink(pre.net_rating.to_numpy(float), h, vc.mu, vc)
    return pd.Series(post, index=pre.index)


def build_features(pre: pd.DataFrame, players: pd.DataFrame, vc: rel.VarianceComponents) -> pd.DataFrame:
    """Features for every pre-break lineup with >= MIN_PRE_POSS possessions. Input must be pre-break only.

    pre:     lineup-window rows (all pre-break lineups of the seasons, not just eligible ones: team totals need them)
    players: `data.pre_break_lineup_players` rows (five per lineup)
    """
    if (pre.window_type != "pre_asb").any() or ("window_type" in players and (players.window_type != "pre_asb").any()):
        raise LeakageError("build_features received post-break rows")
    if "last_team_id" in players:
        raise LeakageError("last_team_id leaks post-break trades (the API ignores the date filter for it)")
    require_dev(pre)
    team = pre.groupby(["season_id", "team_id"]).agg(pts=("pts", "sum"), poss=("poss", "sum"),
                                                     opp_pts=("opp_pts", "sum"), opp_poss=("opp_poss", "sum"))
    # Team net from summed lineup totals (aggregate, then divide). Rows with unknown opp_poss carry 0 seconds.
    known = pre[pre.opp_poss.notna()].groupby(["season_id", "team_id"])[["opp_pts", "opp_poss"]].sum()
    team["team_net"] = 100 * team.pts / team.poss - 100 * known.opp_pts / known.opp_poss

    df = pre[(pre.poss >= MIN_PRE_POSS) & (pre.opp_poss >= MIN_PRE_POSS)].copy()
    df["eb_net"] = eb_net_rating(df, vc)
    df["log_poss"] = np.log(df.poss)
    df = df.join(team[["team_net", "poss"]].rename(columns={"poss": "team_poss"}), on=["season_id", "team_id"])
    p = players.drop(columns=["team_id"], errors="ignore").merge(df[["lineup_id", "team_id", "team_poss"]], on="lineup_id")
    p["share"] = p.player_on_court_poss / p.team_poss
    # Traded = appeared in pre-break lineups of 2+ teams. Ambiguous (traded TO vs AWAY from this team) but
    # leak-free. Do NOT use player_window_stats.last_team_id to resolve the direction: the API fills it
    # with the player's latest team even under a pre-break date filter (Phase 4 finding), so it leaks
    # post-break moves (e.g. Vucevic 2020-21: pre-break games all for ORL, feed says CHI).
    agg = p.groupby("lineup_id").agg(min_player_share=("share", "min"), max_teams=("n_teams", "max"),
                                     n_players=("player_id", "nunique"))
    if (agg.n_players != 5).any():
        raise ValueError("every lineup must have five players with pre-break on-court data")
    df = df.join(agg[["min_player_share"]], on="lineup_id")
    df["has_traded_player"] = (df.lineup_id.map(agg.max_teams) >= 2).astype(int)
    return df.set_index("lineup_id")


def labels(lw: pd.DataFrame, lineup_ids) -> pd.DataFrame:
    """Post-break outcome for the given lineups: possessions after the break (0 if absent)."""
    post = lw[lw.window_type == "post_asb"].set_index("lineup_id").poss
    post_poss = pd.Series(lineup_ids, index=lineup_ids).map(post).fillna(0).astype(int)
    return pd.DataFrame({"post_poss": post_poss, "appears": (post_poss > 0).astype(int),
                         "continues": (post_poss >= MIN_POST_POSS).astype(int)}, index=lineup_ids)


def make_model():
    """Unpenalized logistic regression on standardized features: each coefficient is a log odds ratio per 1 SD."""
    return make_pipeline(StandardScaler(), LogisticRegression(C=np.inf, max_iter=5000))


@dataclass
class CVResult:
    folds: pd.DataFrame          # one row per held-out season
    predictions: pd.Series       # out-of-fold P(continue), aligned to the input rows


def cross_validate(df: pd.DataFrame, y: pd.Series, scheme: str = "loso") -> CVResult:
    """Season-grouped CV. 'loso': leave one season out. 'forward': train on all earlier seasons only.

    Lineups from the same season never appear in both training and validation folds.
    """
    seasons = sorted(df.season_id.unique())
    preds = pd.Series(np.nan, index=df.index)
    rows = []
    for i, s in enumerate(seasons):
        test = df.season_id == s
        train = ~test if scheme == "loso" else df.season_id.isin(seasons[:i])
        if scheme == "forward" and i == 0:
            continue
        model = make_model().fit(df.loc[train, FEATURES], y[train])
        p = model.predict_proba(df.loc[test, FEATURES])[:, 1]
        preds[test] = p
        base = np.full(test.sum(), y[train].mean())
        rows.append({"season": s, "n": int(test.sum()), "rate": float(y[test].mean()),
                     "auc": roc_auc_score(y[test], p), "brier": brier_score_loss(y[test], p),
                     "brier_base": brier_score_loss(y[test], base),
                     "logloss": log_loss(y[test], p), "logloss_base": log_loss(y[test], base)})
    return CVResult(pd.DataFrame(rows), preds)


def odds_ratios(df: pd.DataFrame, y: pd.Series, n_boot: int = 300, seed: int = 0) -> pd.DataFrame:
    """Odds ratio per 1 SD of each feature, with a team-season cluster-bootstrap 95% CI."""
    data = df[FEATURES + ["season_id", "team_id"]].assign(_y=y.values)

    def coefs(d: pd.DataFrame) -> dict[str, float]:
        m = make_model().fit(d[FEATURES], d._y)
        return dict(zip(FEATURES, m[-1].coef_[0]))

    ci = rel.cluster_bootstrap(data, ["season_id", "team_id"], coefs, n_boot=n_boot, seed=seed)
    return np.exp(ci).rename(columns={"estimate": "odds_ratio"})


def calibration_table(p: pd.Series, y: pd.Series, bins: int = 10) -> pd.DataFrame:
    q = pd.qcut(p, bins, labels=False, duplicates="drop")
    g = pd.DataFrame({"p": p, "y": y, "bin": q}).groupby("bin")
    return pd.DataFrame({"n": g.size(), "mean_predicted": g.p.mean(), "observed_rate": g.y.mean()})


def standardized_mean_difference(x: pd.Series, group: pd.Series, weights: pd.Series | None = None) -> float:
    """(mean in selected - mean in full eligible population) / pooled SD. |SMD| < 0.1 is the usual balance rule."""
    w = pd.Series(1.0, index=x.index) if weights is None else weights
    sel = group == 1
    m_sel = np.average(x[sel], weights=w[sel])
    return float((m_sel - x.mean()) / x.std())
