"""Stage 2: fold-fitted features (FeatureBuilder).

`fit(tables, train_seasons)` learns, from the TRAINING seasons' pre-break data only:
  - player-level EB models for on-court ORtg, DRtg, net, on-off net and usage (prior mean depends on
    log possessions: coaches give better players more minutes, so playing time is informative);
  - the lineup-level EB model for the lineup's own history, shrunk toward the team prior.
`transform(tables, lineups)` applies those parameters to any (development) season.

Nothing in fit() reads a target, and fit() refuses rows outside train_seasons. A test proves the
fitted parameters don't change when validation-season data changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..analysis import reliability as rel
from ..analysis.data import HeldOutDataError
from ..config import DEV_SEASONS
from .raw import PreBreakTables, lineup_pairs
from .registry import AUXILIARY, FEATURE_NAMES

FIT_MIN_POSS = 10   # hyperparameters are fitted on units with >= 10 possessions per relevant end (as in Phase 4)


def _per100(num, den) -> np.ndarray:
    num, den = np.asarray(num, float), np.asarray(den, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, 100 * num / den, np.nan)


def _inv(n) -> np.ndarray:
    n = np.asarray(n, float)
    with np.errstate(divide="ignore"):
        return np.where(n > 0, 1 / n, np.nan)


def player_season_rates(t: PreBreakTables) -> pd.DataFrame:
    """One row per (season, player): pooled pre-break totals over every team the player played for, the
    raw rates, their sampling factors h (variance = K·h), and the size n used by the prior."""
    tot = [f"{side}_{c}" for side in ("on", "off") for c in ("poss", "opp_poss", "pts", "opp_pts")]
    p = t.player_team.groupby(["season_id", "player_id"])[tot].sum()
    p = p.join(t.usage.set_index(["season_id", "player_id"])[["usage_poss", "usg_pct"]], how="outer")
    p[tot] = p[tot].fillna(0)
    p["usage_poss"] = p.usage_poss.fillna(0)
    r = pd.DataFrame(index=p.index)
    r["on_poss"] = p.on_poss
    r["off_rating"] = _per100(p.on_pts, p.on_poss)
    r["def_rating"] = _per100(p.on_opp_pts, p.on_opp_poss)
    r["net_rating"] = r.off_rating - r.def_rating
    off_net = _per100(p.off_pts, p.off_poss) - _per100(p.off_opp_pts, p.off_opp_poss)
    r["on_off"] = r.net_rating - off_net
    r["usage"] = 100 * p.usg_pct
    r["h_off_rating"] = _inv(p.on_poss)
    r["h_def_rating"] = _inv(p.on_opp_poss)
    r["h_net_rating"] = r.h_off_rating + r.h_def_rating
    r["h_on_off"] = r.h_net_rating + _inv(p.off_poss) + _inv(p.off_opp_poss)
    r["h_usage"] = _inv(p.usage_poss)
    # n: possessions behind each rate (for the prior's covariate and the fit filter)
    r["n_off_rating"] = r["n_net_rating"] = p.on_poss
    r["n_def_rating"] = p.on_opp_poss
    r["n_on_off"] = np.minimum(np.minimum(p.on_poss, p.on_opp_poss), np.minimum(p.off_poss, p.off_opp_poss))
    r["n_usage"] = p.usage_poss
    return r.reset_index()


PLAYER_RATES = ("off_rating", "def_rating", "net_rating", "on_off", "usage")


@dataclass(frozen=True)
class RateModel:
    """EB model for one player-level rate: prior mean β0 + β1·log(max(n, FIT_MIN_POSS)), between-player
    variance τ², sampling variance K·h. Players with no data (h = NaN) get the prior."""
    vc: rel.VarianceComponents

    def prior(self, n) -> np.ndarray:
        return self.vc.beta[0] + self.vc.beta[1] * np.log(np.maximum(np.asarray(n, float), FIT_MIN_POSS))

    def shrink(self, x, h, n) -> np.ndarray:
        x, h = np.asarray(x, float), np.asarray(h, float)
        prior = self.prior(n)
        ok = np.isfinite(x) & np.isfinite(h)
        out = prior.copy()
        out[ok] = rel.shrink(x[ok], h[ok], prior[ok], self.vc)[0]
        return out


def fit_rate_model(rates: pd.DataFrame, rate: str) -> RateModel:
    d = rates[(rates[f"n_{rate}"] >= FIT_MIN_POSS) & np.isfinite(rates[rate]) & np.isfinite(rates[f"h_{rate}"])]
    return RateModel(rel.fit_variance_components(d[rate], d[f"h_{rate}"], np.log(d[f"n_{rate}"].to_numpy(float))[:, None]))


def lineup_history(t: PreBreakTables, lineups: pd.DataFrame) -> pd.DataFrame:
    """Deterministic lineup- and team-level pre-break quantities for the requested lineups
    (lineup_id, season_id, team_id). Lineups without pre-break rows get zero totals."""
    keys = ["season_id", "team_id"]
    team = t.lineups.groupby(keys)[["poss", "opp_poss", "pts", "opp_pts"]].sum().add_prefix("team_")
    own = t.lineups.set_index("lineup_id")[["poss", "opp_poss", "pts", "opp_pts"]].add_prefix("lu_")
    d = lineups[["lineup_id", "season_id", "team_id"]].join(own, on="lineup_id").join(team, on=keys)
    if d.team_poss.isna().any():
        raise ValueError("lineup from a team without pre-break data")
    for c in ("poss", "opp_poss", "pts", "opp_pts"):
        d[f"lu_{c}"] = d[f"lu_{c}"].fillna(0)
        d[f"loo_{c}"] = d[f"team_{c}"] - d[f"lu_{c}"]
    d["team_off_rating_loo"] = _per100(d.loo_pts, d.loo_poss)
    d["team_def_rating_loo"] = _per100(d.loo_opp_pts, d.loo_opp_poss)
    d["team_net_loo"] = d.team_off_rating_loo - d.team_def_rating_loo
    d["lu_net_raw"] = _per100(d.lu_pts, d.lu_poss) - _per100(d.lu_opp_pts, d.lu_opp_poss)
    d["lu_h"] = rel.sampling_h(d.lu_poss, d.lu_opp_poss)
    return d.set_index("lineup_id")


class FeatureBuilder:
    """Fit on training seasons, transform any development season. See the module docstring."""

    def __init__(self) -> None:
        self.train_seasons_: tuple[str, ...] | None = None
        self.player_models_: dict[str, RateModel] = {}
        self.lineup_vc_: rel.VarianceComponents | None = None

    # ------------------------------------------------------------------ fit
    def fit(self, tables: PreBreakTables, train_seasons) -> FeatureBuilder:
        train_seasons = tuple(sorted(train_seasons))
        if not set(train_seasons) <= set(DEV_SEASONS):     # never fit on held-out data, even with a HoldoutKey
            raise HeldOutDataError(f"FeatureBuilder may only be fitted on development seasons, got {train_seasons}")
        t = tables.subset(train_seasons).validate()
        if not set(t.seasons) <= set(train_seasons) or not t.seasons:
            raise ValueError("fit() received no training data")
        rates = player_season_rates(t)
        self.player_models_ = {r: fit_rate_model(rates, r) for r in PLAYER_RATES}
        # Lineup model: residual of each lineup's raw net from its team prior, over training lineups.
        hist = lineup_history(t, t.lineups[["lineup_id", "season_id", "team_id"]])
        hist = hist[(hist.lu_poss >= FIT_MIN_POSS) & (hist.lu_opp_poss >= FIT_MIN_POSS)]
        self.lineup_vc_ = rel.fit_variance_components(hist.lu_net_raw - hist.team_net_loo, hist.lu_h)
        self.train_seasons_ = train_seasons
        return self

    def params(self) -> dict:
        """Fitted hyperparameters (for reports and fold-stability checks)."""
        out = {"train_seasons": list(self.train_seasons_)}
        for r, m in self.player_models_.items():
            out[f"player_{r}"] = {"beta0": m.vc.beta[0], "beta1_log_poss": m.vc.beta[1], "tau": np.sqrt(m.vc.tau2),
                                  "k": m.vc.k, "n": m.vc.n}
        v = self.lineup_vc_
        out["lineup_vs_team_prior"] = {"mu": v.mu, "tau": np.sqrt(v.tau2), "k": v.k, "n": v.n,
                                       "poss_for_reliability_0.5": v.possessions_for_reliability(0.5)}
        return out

    # ------------------------------------------------------------------ transform
    def transform(self, tables: PreBreakTables, lineups: pd.DataFrame) -> pd.DataFrame:
        """Features for `lineups` (columns lineup_id, season_id, team_id). Index: lineup_id."""
        if self.train_seasons_ is None:
            raise RuntimeError("FeatureBuilder is not fitted")
        t = tables.subset(lineups.season_id.unique()).validate()
        d = lineup_history(t, lineups)

        # Lineup history, shrunk toward the team prior. Without history: B = 0, i.e. exactly the prior.
        v = self.lineup_vc_
        prior = d.team_net_loo + v.mu
        has = d.lu_h.notna()
        B = np.where(has, v.reliability(d.lu_h.fillna(1.0)), 0.0)
        d["lu_reliability"] = B
        d["lu_net_eb_team"] = prior + B * (d.lu_net_raw.fillna(0) - prior).where(has, 0.0)
        d["lu_no_history"] = (~has).astype(int)
        d["lu_log_poss"] = np.log1p(d.lu_poss)

        # Players: shrink each player's pooled pre-break rates, then aggregate over the five.
        rates = player_season_rates(t)
        for r, m in self.player_models_.items():
            rates[f"{r}_eb"] = m.shrink(rates[r], rates[f"h_{r}"], rates[f"n_{r}"])
        mem = t.members[t.members.lineup_id.isin(d.index)][["lineup_id", "player_id"]]
        mem = mem.join(d[["season_id", "team_id", "team_poss"]], on="lineup_id")
        if (mem.groupby("lineup_id").size().reindex(d.index) != 5).any():
            raise ValueError("every lineup must have exactly five players")
        mem = mem.merge(rates, on=["season_id", "player_id"], how="left")
        missing = mem.on_poss.isna()                       # no pre-break data anywhere: prior with n = 0
        for r, m in self.player_models_.items():
            mem.loc[missing, f"{r}_eb"] = m.prior(np.zeros(missing.sum()))
        mem["on_poss"] = mem.on_poss.fillna(0)
        team_on = t.player_team[["season_id", "team_id", "player_id", "on_poss"]].rename(columns={"on_poss": "team_on_poss"})
        mem = mem.merge(team_on, on=["season_id", "team_id", "player_id"], how="left")
        mem["team_on_poss"] = mem.team_on_poss.fillna(0)
        g = mem.assign(share=mem.team_on_poss / mem.team_poss, log_poss=np.log1p(mem.on_poss),
                       new=(mem.team_on_poss == 0).astype(int), none=(mem.on_poss == 0).astype(int)
                       ).groupby("lineup_id")
        agg = pd.DataFrame({
            "p_off_rating_eb_mean": g.off_rating_eb.mean(), "p_def_rating_eb_mean": g.def_rating_eb.mean(),
            "p_net_rating_eb_mean": g.net_rating_eb.mean(), "p_on_off_eb_mean": g.on_off_eb.mean(),
            "p_usage_eb_mean": g.usage_eb.mean(), "p_usage_eb_max": g.usage_eb.max(),
            "p_log_poss_mean": g.log_poss.mean(), "p_team_share_min": g.share.min(),
            "p_n_new_to_team": g.new.sum(), "p_n_no_history": g.none.sum()})
        d = d.join(agg)

        # Familiarity: possessions each of the lineup's 10 pairs shared before the break (for this team).
        pairs = lineup_pairs(t.members[t.members.lineup_id.isin(d.index)]).join(d[["season_id", "team_id"]], on="lineup_id")
        pairs = pairs.merge(t.pairs, on=["season_id", "team_id", "player_a", "player_b"], how="left")
        d["lu_pair_familiarity"] = np.log1p(pairs.shared_poss.fillna(0)).groupby(pairs.lineup_id).mean()

        out = d[list(FEATURE_NAMES) + list(AUXILIARY) + ["season_id", "team_id"]]
        if out[list(FEATURE_NAMES)].isna().any().any():
            bad = out[list(FEATURE_NAMES)].isna().sum()
            raise ValueError(f"features have missing values: {bad[bad > 0].to_dict()}")
        return out
