"""Measurement model for lineup ratings: standard errors, reliability and empirical-Bayes shrinkage.

Model (normal-normal, "true score + sampling error"):

    x_i = theta_i + e_i                      observed net rating of lineup i
    theta_i ~ (mu_i, tau^2)                  true talent: mean mu_i, between-lineup variance tau^2
    e_i | theta_i ~ (0, K * h_i)             sampling error, independent of theta_i
    h_i = 1/poss_i + 1/opp_poss_i            (rating = 100 * mean points per possession, on each end)

K = 100^2 * sigma^2, where sigma^2 is the variance of points scored on a single possession. Assumptions:
possessions are independent, and sigma^2 is the same on offense and defense and for every lineup. These are
approximations. The split-half analysis (home vs road games) tests them on real data.

Both tau^2 and K are estimated by the METHOD OF MOMENTS from E[(x_i - mu_i)^2] = tau^2 + K * h_i:
regressing squared residuals on h_i gives tau^2 as the intercept and K as the slope.
The regression uses iteratively reweighted least squares, with weights 1/(tau^2 + K h_i)^2 (the
variance of a squared normal residual), so that noisy tiny lineups don't dominate the fit.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

Z95 = 1.959963984540054  # standard normal 97.5% quantile


def sampling_h(poss, opp_poss) -> np.ndarray:
    """h = 1/poss + 1/opp_poss; NaN when either side has no possessions (rating undefined)."""
    p = np.asarray(poss, dtype=float)
    q = np.asarray(opp_poss, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where((p > 0) & (q > 0), 1.0 / p + 1.0 / q, np.nan)


@dataclass(frozen=True)
class VarianceComponents:
    beta: tuple[float, ...]   # mean model coefficients (beta[0] = mu when there are no covariates)
    tau2: float               # between-lineup variance of TRUE net rating
    k: float                  # sampling variance per unit of h (100^2 x per-possession variance)
    n: int                    # observations used in the fit

    @property
    def mu(self) -> float:
        return self.beta[0]

    @property
    def sigma_per_possession(self) -> float:
        """Implied SD of points on one possession (points, not per 100)."""
        return float(np.sqrt(self.k) / 100)

    def sampling_var(self, h) -> np.ndarray:
        return self.k * np.asarray(h, dtype=float)

    def standard_error(self, h) -> np.ndarray:
        return np.sqrt(self.sampling_var(h))

    def reliability(self, h) -> np.ndarray:
        """Share of observed variance that is true signal: tau^2 / (tau^2 + K h). Also the shrinkage factor B."""
        return self.tau2 / (self.tau2 + self.sampling_var(h))

    def reliability_at(self, possessions) -> np.ndarray:
        """Reliability for a lineup with `possessions` on each end (h = 2/n)."""
        return self.reliability(2.0 / np.asarray(possessions, dtype=float))

    def possessions_for_reliability(self, target: float) -> float:
        """Possessions per end needed for reliability `target`: solves tau^2/(tau^2 + 2K/n) = target."""
        if not 0 < target < 1:
            raise ValueError("target must be in (0, 1)")
        return float(2 * self.k * target / (self.tau2 * (1 - target)))


def fit_variance_components(x, h, covariates: np.ndarray | None = None, max_iter: int = 200,
                            tol: float = 1e-10) -> VarianceComponents:
    """Method-of-moments estimate of (mean model, tau^2, K) from observed ratings x and sampling factors h.

    covariates: optional (n, p) matrix for the prior mean mu_i = [1, covariates] @ beta (e.g. log possessions).
    """
    x = np.asarray(x, dtype=float)
    h = np.asarray(h, dtype=float)
    ok = np.isfinite(x) & np.isfinite(h)
    X = np.ones((len(x), 1)) if covariates is None else np.column_stack([np.ones(len(x)), covariates])
    x, h, X = x[ok], h[ok], X[ok]
    if len(x) < 3 * X.shape[1] + 3:
        raise ValueError("too few observations")

    # Start: OLS mean, OLS moment regression.
    beta = np.linalg.lstsq(X, x, rcond=None)[0]
    tau2, k = _moment_regression(x - X @ beta, h, np.ones_like(h))
    for _ in range(max_iter):
        v = tau2 + k * h                                   # total variance of each observation
        w = 1.0 / v
        beta = np.linalg.solve(X.T @ (X * w[:, None]), X.T @ (w * x))   # precision-weighted mean model
        new_tau2, new_k = _moment_regression(x - X @ beta, h, 1.0 / v**2)
        done = abs(new_tau2 - tau2) <= tol * max(1.0, tau2) and abs(new_k - k) <= tol * max(1.0, k)
        tau2, k = new_tau2, new_k
        if done:
            break
    return VarianceComponents(tuple(float(b) for b in beta), float(tau2), float(k), int(len(x)))


def _moment_regression(resid: np.ndarray, h: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """WLS of resid^2 on [1, h]; tau^2 is truncated at a tiny positive value (a variance can't be negative)."""
    A = np.column_stack([np.ones_like(h), h])
    coef = np.linalg.solve(A.T @ (A * w[:, None]), A.T @ (w * resid**2))
    return max(float(coef[0]), 1e-6), max(float(coef[1]), 1e-6)


def shrink(x, h, prior_mean, vc: VarianceComponents) -> tuple[np.ndarray, np.ndarray]:
    """Empirical-Bayes posterior mean and SD of each lineup's true rating.

    posterior mean = prior + B (x - prior),   B = tau^2 / (tau^2 + K h)   (B = reliability)
    posterior var  = B * K h  = 1 / (1/tau^2 + 1/(K h))
    Small samples (large h) -> B near 0 -> pulled almost all the way to the prior.
    """
    x = np.asarray(x, dtype=float)
    B = vc.reliability(h)
    post = np.asarray(prior_mean, dtype=float) + B * (x - prior_mean)
    return post, np.sqrt(B * vc.sampling_var(h))


def confidence_interval(x, h, vc: VarianceComponents, z: float = Z95) -> tuple[np.ndarray, np.ndarray]:
    """Frequentist interval for one lineup's true rating, x +/- z * SE (normal approximation: CLT over possessions)."""
    se = vc.standard_error(h)
    return np.asarray(x) - z * se, np.asarray(x) + z * se


def spearman_brown(r, factor: float = 2.0):
    """Reliability of a measure `factor` times as long as one whose reliability is r (classical test theory)."""
    r = np.asarray(r, dtype=float)
    return factor * r / (1 + (factor - 1) * r)


@dataclass(frozen=True)
class SplitHalfResult:
    n: int
    r: float                  # Pearson correlation between the two halves
    spearman_brown: float     # implied reliability of the combined (full-window) rating
    cov: float                # Cov(x_a, x_b): estimates tau^2 directly (independent errors), no sampling model
    mean_h_a: float
    mean_h_b: float
    diff: VarianceComponents  # model fitted to d = x_a - x_b: K (sampling) and tau2 (true home/road heterogeneity)

    def predicted_r(self, vc: VarianceComponents) -> float:
        """Correlation the measurement model `vc` predicts for these half-samples."""
        va = vc.tau2 + vc.k * self.mean_h_a
        vb = vc.tau2 + vc.k * self.mean_h_b
        return float(vc.tau2 / np.sqrt(va * vb))


def split_half(xa, ha, xb, hb) -> SplitHalfResult:
    """Split-half analysis for two DISJOINT half-samples of the same lineups (e.g. home vs road games).

    Because the halves share no possessions, their sampling errors are independent, so
      Cov(x_a, x_b) = Var(true rating)                 (tau^2, identified WITHOUT any sampling model)
      Var(x_a - x_b) = Var(true a-b gap) + K (h_a + h_b)   (K, identified from the differences)
    """
    xa, ha, xb, hb = (np.asarray(v, dtype=float) for v in (xa, ha, xb, hb))
    ok = np.isfinite(xa) & np.isfinite(xb) & np.isfinite(ha) & np.isfinite(hb)
    xa, ha, xb, hb = xa[ok], ha[ok], xb[ok], hb[ok]
    r = float(np.corrcoef(xa, xb)[0, 1])
    return SplitHalfResult(
        n=int(ok.sum()), r=r, spearman_brown=float(spearman_brown(r)), cov=float(np.cov(xa, xb)[0, 1]),
        mean_h_a=float(ha.mean()), mean_h_b=float(hb.mean()),
        diff=fit_variance_components(xa - xb, ha + hb))


def cluster_bootstrap(df: pd.DataFrame, cluster: str | list[str], stat: Callable[[pd.DataFrame], dict[str, float]],
                      n_boot: int = 500, seed: int = 0, level: float = 0.95) -> pd.DataFrame:
    """Percentile bootstrap CIs, resampling whole clusters (e.g. team-seasons) with replacement.

    Lineups of one team share players and opponents, so they aren't independent. Resampling
    individual lineups would understate the uncertainty.
    """
    rng = np.random.default_rng(seed)
    groups = [g for _, g in df.groupby(cluster, sort=False)]
    point = stat(df)
    reps = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(groups), len(groups))
        reps.append(stat(pd.concat([groups[i] for i in idx], ignore_index=True)))
    reps = pd.DataFrame(reps)
    a = (1 - level) / 2
    return pd.DataFrame({"estimate": pd.Series(point), "lo": reps.quantile(a), "hi": reps.quantile(1 - a)})


def kish_effective_n(w) -> float:
    w = np.asarray(w, dtype=float)
    return float(w.sum() ** 2 / (w**2).sum())


def weighted_mean(x, w) -> float:
    return float(np.average(np.asarray(x, dtype=float), weights=np.asarray(w, dtype=float)))
