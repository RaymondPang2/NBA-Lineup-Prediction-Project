"""Phase 4: exploratory analysis, statistical reliability, shrinkage and selection (development seasons only).

Reads the loaded database (read-only) and writes:
    reports/phase4/figures/*.png           publication figures
    reports/phase4/findings.json           every number quoted in docs/eda_reliability.md (for React / Power BI)
    reports/phase4/reliability_curve.csv   reliability vs possessions, with a bootstrap band (for the dashboards)

Only 2018-19 .. 2023-24 are read (`nba_lineups.analysis.data` enforces it). 2024-25 and 2025-26 stay held out.

Usage:  .venv/bin/python scripts/phase4/eda_reliability.py [--boot 300]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from nba_lineups.analysis import continuation as cont
from nba_lineups.analysis import data
from nba_lineups.analysis import reliability as rel
from nba_lineups.analysis.plotting import AQUA, BLUE, INK_2, MUTED, ORANGE, apply_style, save
from nba_lineups.config import DEV_SEASONS, IRREGULAR_SEASONS, PROJECT_ROOT
from nba_lineups.db.connection import connect

OUT = PROJECT_ROOT / "reports" / "phase4"
FIG = OUT / "figures"
FIT_MIN_POSS = 10                    # measurement model fitted on lineups with >= 10 possessions on each end
THRESHOLDS = (25, 100, 300)          # possession thresholds compared throughout
POSS_BINS = [0, 5, 10, 25, 50, 100, 200, 400, 10_000]
F: dict = {"seasons": list(DEV_SEASONS), "held_out_never_read": ["2024-25", "2025-26"]}


def heading(t: str) -> None:
    print(f"\n=== {t}")


def wavg(x, w) -> float:
    return rel.weighted_mean(x, w)


def wrmse(pred, y, w) -> float:
    return float(np.sqrt(np.average((np.asarray(pred) - np.asarray(y)) ** 2, weights=w)))


def wslope(x, y, w) -> float:
    """Weighted least-squares slope of y on x."""
    x, y, w = (np.asarray(v, float) for v in (x, y, w))
    xm, ym = np.average(x, weights=w), np.average(y, weights=w)
    return float(np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2))


def fit_vc(df: pd.DataFrame, col: str = "net_rating", covariates=None) -> rel.VarianceComponents:
    d = df[(df.poss >= FIT_MIN_POSS) & (df.opp_poss >= FIT_MIN_POSS)]
    cov = None if covariates is None else covariates(d)
    return rel.fit_variance_components(d[col], rel.sampling_h(d.poss, d.opp_poss), cov)


# ---------------------------------------------------------------------------------------------------- 1
def distributions(lw: pd.DataFrame) -> None:
    heading("1. Distributions (both windows, development seasons)")
    rated = lw[lw.net_rating.notna()]
    tot = lw.poss.sum()
    rows = []
    for lo in (0, *THRESHOLDS):
        d = rated[rated.poss >= max(lo, 1)]
        rows.append({
            "min_poss": lo, "lineup_windows": len(d), "share_of_all_poss": d.poss.sum() / tot,
            "minutes_median": d.minutes.median(),
            "ortg_pooled": 100 * d.pts.sum() / d.poss.sum(),
            "drtg_pooled": 100 * d.opp_pts.sum() / d.opp_poss.sum(),
            "ortg_sd": d.off_rating.std(), "drtg_sd": d.def_rating.std(), "net_sd": d.net_rating.std(),
            "net_p05": d.net_rating.quantile(.05), "net_p95": d.net_rating.quantile(.95)})
    t = pd.DataFrame(rows)
    print(t.round(3).to_string(index=False))
    F["distributions"] = t.round(4).to_dict("records")
    q = lw.poss.quantile([.25, .5, .75, .9, .99])
    F["possessions_quantiles"] = {f"p{int(k*100)}": float(v) for k, v in q.items()}
    F["minutes_per_possession_median"] = float((lw.minutes / lw.poss.where(lw.poss > 0)).median())
    print("possession quantiles:", F["possessions_quantiles"])

    # fig01: possessions and minutes
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8))
    # Integer-aware log bins: edges at k - 0.5 so small counts (1, 2, 3 ...) don't leave empty bins.
    bins = np.unique(np.round(np.logspace(0, np.log10(lw.poss.max() + 1), 45))) - 0.5
    ax[0].hist(lw.poss[lw.poss > 0], bins=bins, color=BLUE, edgecolor="white", linewidth=0.5)
    ax[0].set(xscale="log", xlabel="Possessions (log scale)", ylabel="Lineup-windows",
              title="Most lineups play a few possessions")
    mb = np.logspace(np.log10(0.05), np.log10(lw.minutes.max() + 1), 40)
    ax[1].hist(lw.minutes[lw.minutes > 0], bins=mb, color=BLUE, edgecolor="white", linewidth=0.5)
    ax[1].set(xscale="log", xlabel="Minutes (log scale)", ylabel="Lineup-windows", title="Minutes mirror possessions")
    s = np.sort(lw.poss.to_numpy())[::-1]
    ax[2].plot(np.arange(1, len(s) + 1) / len(s) * 100, np.cumsum(s) / s.sum() * 100, color=BLUE)
    for pct in (1, 5, 20):
        y = np.cumsum(s)[int(len(s) * pct / 100) - 1] / s.sum() * 100
        ax[2].plot(pct, y, "o", color=BLUE, ms=6)
        ax[2].annotate(f"top {pct}% of lineups\n= {y:.0f}% of possessions", (pct, y), xytext=(8, -18),
                       textcoords="offset points", fontsize=8, color=INK_2)
    ax[2].set(xscale="log", xlim=(0.1, 100), xlabel="Lineups ranked by possessions (top %, log scale)",
              ylabel="Cumulative share of possessions (%)", title="Concentration of playing time")
    save(fig, FIG / "fig01_possessions_minutes.png")

    # fig02: rating distributions narrow as the sample grows
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8), sharey=False)
    for a, (col, label) in zip(ax, [("off_rating", "Offensive rating"), ("def_rating", "Defensive rating"),
                                    ("net_rating", "Net rating")]):
        edges = np.linspace(-60, 60, 61) if col == "net_rating" else np.linspace(60, 160, 51)
        for lo, color in zip(THRESHOLDS, (AQUA, ORANGE, BLUE)):
            d = rated.loc[rated.poss >= lo, col].clip(edges[0], edges[-1])
            a.hist(d, bins=edges, density=True, histtype="step", linewidth=2, color=color,
                   label=f"≥ {lo} poss (n={len(d):,}, SD {d.std():.1f})")
        a.set(xlabel=f"{label} (per 100 possessions; tails clipped)", ylabel="Density",
              title=f"{label}: spread shrinks with sample size")
        a.set_ylim(0, a.get_ylim()[1] * 1.35)          # headroom so the legend never covers the curves
        a.legend(loc="upper left", fontsize=7.5)
    save(fig, FIG / "fig02_rating_distributions.png")

    # fig03: offense vs defense
    d = rated[rated.poss >= 100]
    fig, ax = plt.subplots(figsize=(6, 5.4))
    ax.scatter(d.off_rating, d.def_rating, s=10, color=BLUE, alpha=0.45, linewidths=0)
    lims = (75, 145)
    for net in (-20, -10, 0, 10, 20):
        xs = np.array(lims)
        ax.plot(xs, xs - net, color=MUTED, lw=0.8, ls="--" if net else "-", zorder=0)
        ax.annotate(f"net {net:+d}" if net else "net 0", (lims[1] - 2, lims[1] - 2 - net), fontsize=7.5,
                    color=INK_2, ha="right", va="bottom")
    r = np.corrcoef(d.off_rating, d.def_rating)[0, 1]
    ax.set(xlim=lims, ylim=lims, xlabel="Offensive rating", ylabel="Defensive rating (lower is better)",
           title=f"Offense vs defense, lineups with ≥ 100 possessions (n={len(d):,}, r = {r:.2f})")
    F["ortg_drtg_corr_100plus"] = float(r)
    save(fig, FIG / "fig03_offense_vs_defense.png")


# ---------------------------------------------------------------------------------------------------- 2
def measurement_model(pre: pd.DataFrame, n_boot: int) -> rel.VarianceComponents:
    heading("2. Measurement model (pre-break windows): tau^2, K, standard errors")
    vc = fit_vc(pre)
    print(f"main fit (>= {FIT_MIN_POSS} poss each end, n={vc.n:,}): mu={vc.mu:.2f} tau={np.sqrt(vc.tau2):.2f} "
          f"(tau2={vc.tau2:.1f}) K={vc.k:.0f} sigma/poss={vc.sigma_per_possession:.3f}")

    def stats(d: pd.DataFrame) -> dict[str, float]:
        v = fit_vc(d)
        return {"mu": v.mu, "tau": np.sqrt(v.tau2), "k": v.k, "sigma_per_poss": v.sigma_per_possession,
                "poss_rel50": v.possessions_for_reliability(.5), "poss_rel70": v.possessions_for_reliability(.7)}

    boot = rel.cluster_bootstrap(pre, ["season_id", "team_id"], stats, n_boot=n_boot, seed=1)
    print(boot.round(3))
    F["measurement_model"] = {"fit_min_poss_each_end": FIT_MIN_POSS, "n": vc.n, **{
        k: {"estimate": float(r.estimate), "ci95": [float(r.lo), float(r.hi)]} for k, r in boot.iterrows()}}

    # sensitivity: thresholds, leave-one-season-out, irregular seasons, offense/defense separately
    sens = []
    for lo in (5, 10, 25, 50, 100):
        d = pre[(pre.poss >= lo) & (pre.opp_poss >= lo)]
        v = rel.fit_variance_components(d.net_rating, rel.sampling_h(d.poss, d.opp_poss))
        sens.append({"variant": f"fit on >= {lo} poss", "n": v.n, "tau": np.sqrt(v.tau2), "k": v.k,
                     "poss_rel50": v.possessions_for_reliability(.5)})
    for s in DEV_SEASONS:
        v = fit_vc(pre[pre.season_id == s])
        sens.append({"variant": f"season {s} only", "n": v.n, "tau": np.sqrt(v.tau2), "k": v.k,
                     "poss_rel50": v.possessions_for_reliability(.5)})
    v = fit_vc(pre[~pre.season_id.isin(IRREGULAR_SEASONS)])
    sens.append({"variant": "excluding 2019-20 and 2020-21", "n": v.n, "tau": np.sqrt(v.tau2), "k": v.k,
                 "poss_rel50": v.possessions_for_reliability(.5)})
    sens = pd.DataFrame(sens)
    print(sens.round(2).to_string(index=False))
    F["measurement_model_sensitivity"] = sens.round(3).to_dict("records")

    sides = {}
    for col, den in (("off_rating", "poss"), ("def_rating", "opp_poss")):
        d = pre[(pre.poss >= FIT_MIN_POSS) & (pre.opp_poss >= FIT_MIN_POSS)]
        v = rel.fit_variance_components(d[col], 1.0 / d[den])
        sides[col] = {"mean": v.mu, "tau": float(np.sqrt(v.tau2)), "k": v.k,
                      "poss_rel50": float(v.k / v.tau2)}   # one end only: h = 1/n
    print("offense / defense separately:", {k: {kk: round(vv, 2) for kk, vv in s.items()} for k, s in sides.items()})
    F["offense_defense_components"] = sides

    # observed vs predicted spread by possession bin (including bins NOT used in the fit)
    d = pre[pre.net_rating.notna() & (pre.poss > 0) & (pre.opp_poss > 0)].copy()
    d["h"] = rel.sampling_h(d.poss, d.opp_poss)
    d["bin"] = pd.cut(d.poss, POSS_BINS, right=False)
    g = d.groupby("bin", observed=True)
    tab = pd.DataFrame({"n": g.size(), "mean_net": g.net_rating.mean(), "sd_observed": g.net_rating.std(),
                        "sd_predicted": g.h.apply(lambda h: np.sqrt(vc.tau2 + vc.k * h.mean())),
                        "sd_sampling_only": g.h.apply(lambda h: np.sqrt(vc.k * h.mean())),
                        "share_signal": g.h.apply(lambda h: vc.tau2 / (vc.tau2 + vc.k * h.mean()))})
    tab.index = tab.index.astype(str)
    print(tab.round(2))
    F["sd_by_possessions"] = tab.round(3).reset_index().rename(columns={"bin": "poss_bin"}).to_dict("records")

    # fig04: funnel plot
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.scatter(d.poss, d.net_rating.clip(-150, 150), s=3, color=BLUE, alpha=0.12, linewidths=0, rasterized=True,
               label="Lineup (pre-break window)")
    n = np.logspace(0, np.log10(d.poss.max()), 200)
    noise = rel.Z95 * np.sqrt(vc.k * 2 / n)
    total = rel.Z95 * np.sqrt(vc.tau2 + vc.k * 2 / n)
    ax.plot(n, vc.mu + noise, color=ORANGE, label="95% band if every lineup were truly average (sampling noise only)")
    ax.plot(n, vc.mu - noise, color=ORANGE)
    ax.plot(n, vc.mu + total, color=INK_2, ls="--", lw=1.4, label="95% band: noise + real differences (model)")
    ax.plot(n, vc.mu - total, color=INK_2, ls="--", lw=1.4)
    inside = np.abs(d.net_rating - vc.mu) <= rel.Z95 * np.sqrt(vc.k * d.h)
    big = d.poss >= 100
    ax.set(xscale="log", ylim=(-150, 150), xlabel="Possessions (log scale)", ylabel="Net rating (clipped to ±150)",
           title=f"Funnel plot: {inside.mean():.0%} of all lineups (and {inside[big].mean():.0%} of those with "
                 f"≥ 100 possessions) sit inside the pure-noise band")
    ax.legend(loc="lower right", fontsize=8)
    F["funnel_share_inside_noise_band"] = {"all": float(inside.mean()), "poss_ge_100": float(inside[big].mean())}
    save(fig, FIG / "fig04_funnel.png")

    # fig05: observed vs predicted SD
    fig, ax = plt.subplots(figsize=(8, 4.6))
    x = np.arange(len(tab))
    ax.plot(x, tab.sd_observed, "o-", color=BLUE, ms=8, label="Observed SD of net rating")
    ax.plot(x, tab.sd_predicted, "s--", color=ORANGE, ms=7, lw=1.6, label="Model: sqrt(τ² + K·h)")
    ax.plot(x, tab.sd_sampling_only, ":", color=INK_2, lw=1.6, label="Sampling noise only: sqrt(K·h)")
    ax.axhline(np.sqrt(vc.tau2), color=AQUA, lw=1.6, label=f"True-talent SD τ = {np.sqrt(vc.tau2):.1f}")
    ax.set(yscale="log", xticks=x, xlabel="Possessions bin", ylabel="SD of net rating (log scale)",
           title="One two-parameter model explains the spread at every sample size")
    ax.set_xticklabels([b.replace(", ", "–").strip("[)") for b in tab.index], fontsize=8)
    ax.legend(fontsize=8)
    save(fig, FIG / "fig05_sd_by_possessions.png")
    return vc


# ---------------------------------------------------------------------------------------------------- 3
def reliability_curve(pre: pd.DataFrame, vc: rel.VarianceComponents, n_boot: int) -> pd.DataFrame:
    heading("3. Reliability vs sample size")
    grid = np.unique(np.round(np.logspace(np.log10(10), np.log10(3000), 60)).astype(int))
    rng = np.random.default_rng(2)
    groups = [g for _, g in pre.groupby(["season_id", "team_id"])]
    curves = []
    for _ in range(n_boot):
        b = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        curves.append(fit_vc(b).reliability_at(grid))
    curves = np.array(curves)
    curve = pd.DataFrame({"possessions": grid, "reliability": vc.reliability_at(grid),
                          "lo": np.quantile(curves, .025, axis=0), "hi": np.quantile(curves, .975, axis=0)})
    curve.round(4).to_csv(OUT / "reliability_curve.csv", index=False)

    targets = {}
    for t in (0.5, 0.7, 0.8):
        n_t = vc.possessions_for_reliability(t)
        reach = pre[pre.poss >= n_t]
        targets[str(t)] = {"possessions": n_t, "lineups_reaching_per_season": len(reach) / len(DEV_SEASONS),
                           "share_of_possessions": float(reach.poss.sum() / pre.poss.sum())}
    for n in THRESHOLDS:
        targets[f"at_{n}_poss"] = {"reliability": float(vc.reliability_at(n))}
    F["reliability"] = targets
    print(json.dumps(targets, indent=1, default=float))

    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.fill_between(curve.possessions, curve.lo, curve.hi, color=BLUE, alpha=0.18, linewidth=0,
                    label="95% bootstrap band (team-season clusters)")
    ax.plot(curve.possessions, curve.reliability, color=BLUE, label="Reliability = τ² / (τ² + K·2/n)")
    for t in (0.5, 0.7):
        n_t = targets[str(t)]["possessions"]
        ax.axhline(t, color=MUTED, lw=0.8, ls=":")
        ax.plot(n_t, t, "o", color=BLUE, ms=7)
        ax.annotate(f"{t:.0%} at ~{n_t:,.0f} poss", (n_t, t), xytext=(-12, 8), textcoords="offset points",
                    ha="right", fontsize=8.5, color=INK_2)
    for n in THRESHOLDS:
        ax.axvline(n, color=GRIDLINE, lw=0.8)
        ax.annotate(f"{n}", (n, 0.02), fontsize=8, color=INK_2, ha="center")
    ax.set(xscale="log", ylim=(0, 1), xlabel="Possessions per end (log scale)", ylabel="Reliability",
           title="How much of a lineup's net rating is signal?")
    ax.legend(loc="upper left", fontsize=8)
    save(fig, FIG / "fig06_reliability_curve.png")
    return curve


GRIDLINE = "#d6d5d0"


# ---------------------------------------------------------------------------------------------------- 4
def split_half_analysis(splits: pd.DataFrame, pre: pd.DataFrame, vc: rel.VarianceComponents,
                        games: pd.DataFrame, n_boot: int) -> None:
    heading("4. Split-half reliability: home vs road games (disjoint, interleaved halves)")
    s = splits.copy()
    for side in ("home", "road"):
        s[f"h_{side}"] = rel.sampling_h(s[f"poss_{side}"], s[f"opp_poss_{side}"])
    F["split_half_lineups_with_both_halves"] = int((s.h_home.notna() & s.h_road.notna()).sum())
    rows = []
    for lo in (25, 50, 100):
        d = s[(s[["poss_home", "opp_poss_home", "poss_road", "opp_poss_road"]] >= lo).all(axis=1)]
        sh = rel.split_half(d.net_rating_home, d.h_home, d.net_rating_road, d.h_road)

        def r_of(b: pd.DataFrame) -> dict[str, float]:
            q = rel.split_half(b.net_rating_home, b.h_home, b.net_rating_road, b.h_road)
            return {"r": q.r, "cov": q.cov, "k_diff": q.diff.k}

        ci = rel.cluster_bootstrap(d, ["season_id", "team_id"], r_of, n_boot=n_boot, seed=3)
        z = (d.net_rating_home - d.net_rating_road - sh.diff.mu) / np.sqrt(vc.k * (d.h_home + d.h_road))
        rows.append({"min_poss_each_half_each_end": lo, "n": sh.n, "r": sh.r, "r_lo": ci.loc["r", "lo"],
                     "r_hi": ci.loc["r", "hi"], "r_predicted_by_model": sh.predicted_r(vc),
                     "spearman_brown_full": sh.spearman_brown,
                     "cov_tau2": sh.cov, "cov_lo": ci.loc["cov", "lo"], "cov_hi": ci.loc["cov", "hi"],
                     "k_from_differences": sh.diff.k, "k_lo": ci.loc["k_diff", "lo"], "k_hi": ci.loc["k_diff", "hi"],
                     "home_minus_road_mean": sh.diff.mu, "z_sd": float(z.std()),
                     "coverage_95": float((z.abs() <= rel.Z95).mean())})
    t = pd.DataFrame(rows)
    print(t.round(3).to_string(index=False))
    print(f"funnel-model values for comparison: tau2={vc.tau2:.1f}, K={vc.k:.0f}")
    F["split_half"] = t.round(4).to_dict("records")

    # Team level: classic odd/even split of pre-break games (point differential per game).
    g = games[games.window_type == "pre_asb"].copy()
    g["half"] = g.groupby(["season_id", "team_id"]).cumcount() % 2
    w = g.pivot_table(index=["season_id", "team_id"], columns="half", values="plus_minus", aggfunc="mean")
    r_team = float(np.corrcoef(w[0], w[1])[0, 1])
    F["team_odd_even_split_half"] = {"n_team_seasons": len(w), "r": r_team,
                                     "spearman_brown": float(rel.spearman_brown(r_team))}
    print(f"team odd/even games: n={len(w)} r={r_team:.3f} Spearman-Brown={rel.spearman_brown(r_team):.3f}")

    # fig07
    d = s[(s[["poss_home", "opp_poss_home", "poss_road", "opp_poss_road"]] >= 50).all(axis=1)]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.8), gridspec_kw={"width_ratios": [1.1, 1]})
    ax[0].scatter(d.net_rating_home, d.net_rating_road, s=10, color=BLUE, alpha=0.4, linewidths=0)
    m, b = np.polyfit(d.net_rating_home, d.net_rating_road, 1)
    xs = np.array([-60, 60])
    ax[0].plot(xs, m * xs + b, color=ORANGE, label=f"Least-squares fit (slope {m:.2f})")
    ax[0].plot(xs, xs, color=MUTED, lw=1, ls="--", label="y = x (perfect reliability)")
    r50 = t.loc[t.min_poss_each_half_each_end == 50].iloc[0]
    ax[0].set(xlim=(-60, 60), ylim=(-60, 60), xlabel="Net rating in HOME games", ylabel="Net rating in ROAD games",
              title=f"Same lineup, disjoint games: r = {r50.r:.2f} (n = {int(r50.n):,}, ≥ 50 poss per half)")
    ax[0].legend(loc="upper left", fontsize=8)
    y = np.arange(len(t))
    ax[1].errorbar(t.r, y + 0.12, xerr=[t.r - t.r_lo, t.r_hi - t.r], fmt="o", color=BLUE, ms=8, capsize=3,
                   label="Observed r (95% cluster-bootstrap CI)")
    ax[1].plot(t.r_predicted_by_model, y - 0.12, "D", color=ORANGE, ms=7,
               label="Predicted by the measurement model")
    ax[1].set(yticks=y, xlim=(0, 0.6), xlabel="Correlation between home and road net rating",
              title="Model predictions vs observed split-half r")
    ax[1].set_yticklabels([f"≥ {v} poss/half\n(n = {n:,})" for v, n in zip(t.min_poss_each_half_each_end, t.n)])
    ax[1].legend(loc="lower right", fontsize=8)
    save(fig, FIG / "fig07_split_half.png")


# ---------------------------------------------------------------------------------------------------- 5
def uncertainty_examples(vc: rel.VarianceComponents) -> None:
    heading("5. Standard errors and intervals for typical sample sizes (equal possessions on both ends)")
    rows = []
    for n in (25, 50, 100, 250, 500, 1000, 2000):
        h = 2.0 / n
        B = float(vc.reliability(h))
        rows.append({"possessions": n, "se": float(vc.standard_error(h)), "ci95_half_width": rel.Z95 * float(vc.standard_error(h)),
                     "reliability_B": B, "eb_posterior_sd": float(np.sqrt(B * vc.k * h)),
                     "eb_interval_half_width": rel.Z95 * float(np.sqrt(B * vc.k * h))})
    t = pd.DataFrame(rows)
    print(t.round(2).to_string(index=False))
    F["uncertainty_by_possessions"] = t.round(3).to_dict("records")


# ---------------------------------------------------------------------------------------------------- 6
def team_loo_prior(pre: pd.DataFrame) -> pd.Series:
    """Team pre-break net rating from all OTHER lineups of the team (aggregate, then divide)."""
    known = pre.opp_poss.notna()
    keys = [pre.season_id, pre.team_id]
    tp, tposs = pre.groupby(keys).pts.transform("sum"), pre.groupby(keys).poss.transform("sum")
    top = pre.opp_pts.where(known, 0).groupby(keys).transform("sum")
    topp = pre.opp_poss.fillna(0).groupby(keys).transform("sum")
    return 100 * (tp - pre.pts) / (tposs - pre.poss) - 100 * (top - pre.opp_pts) / (topp - pre.opp_poss)


K_MAIN = float("nan")   # set from the main measurement-model fit in main()
N_BOOT = 300


def shrinkage(lw: pd.DataFrame, pre: pd.DataFrame, n_boot: int) -> pd.DataFrame:
    heading("6. Empirical-Bayes shrinkage: does it predict the post-break rating better? (leave-one-season-out)")
    pre = pre.copy()
    pre["h"] = rel.sampling_h(pre.poss, pre.opp_poss)
    pre["team_prior"] = team_loo_prior(pre)
    post = lw[lw.window_type == "post_asb"].set_index("lineup_id")
    out = []
    params = []
    for s in DEV_SEASONS:
        train, test = pre[pre.season_id != s], pre[(pre.season_id == s) & pre.h.notna()].copy()
        # Hyperparameters from OTHER seasons' pre-break data only. No post-break data is used for fitting.
        v0 = fit_vc(train)
        v1 = fit_vc(train, covariates=lambda d: np.log(d.poss.to_numpy(float))[:, None])
        v2 = fit_vc(train.assign(net_rating=train.net_rating - train.team_prior))
        params.append({"season": s, "league_tau": np.sqrt(v0.tau2), "poss_prior_slope": v1.beta[1],
                       "poss_prior_tau": np.sqrt(v1.tau2), "team_prior_tau": np.sqrt(v2.tau2)})
        test["pred_league_mean"] = v0.mu
        test["pred_raw"] = test.net_rating
        test["pred_eb_league"] = rel.shrink(test.net_rating, test.h, v0.mu, v0)[0]
        prior1 = v1.beta[0] + v1.beta[1] * np.log(test.poss)
        test["pred_eb_poss"] = rel.shrink(test.net_rating, test.h, prior1, v1)[0]
        prior2 = test.team_prior + v2.mu
        test["pred_eb_team"] = rel.shrink(test.net_rating, test.h, prior2, v2)[0]
        test["pred_team_prior"] = prior2
        out.append(test)
    ev = pd.concat(out).join(post[["poss", "opp_poss", "net_rating"]].add_prefix("post_"), on="lineup_id")
    ev = ev[(ev.post_poss >= 25) & (ev.post_opp_poss >= 25)]
    F["shrinkage_hyperparameters_by_held_out_season"] = pd.DataFrame(params).round(3).to_dict("records")
    preds = {"pred_league_mean": "League mean (no lineup info)", "pred_raw": "Raw pre-break rating",
             "pred_eb_league": "EB → league mean", "pred_eb_poss": "EB → possession-informed prior",
             "pred_team_prior": "Team prior only (other lineups)", "pred_eb_team": "EB → team prior"}

    def metrics(d: pd.DataFrame) -> dict[str, float]:
        res = {}
        for c in preds:
            res[f"rmse_{c}"] = wrmse(d[c], d.post_net_rating, d.post_poss)
            # A slope is meaningless for the league-mean predictor (constant within each season).
            res[f"slope_{c}"] = np.nan if c == "pred_league_mean" else wslope(d[c], d.post_net_rating, d.post_poss)
        for c in preds:
            res[f"gain_{c}"] = res["rmse_pred_raw"] - res[f"rmse_{c}"]
            res[f"gain_vs_mean_{c}"] = res["rmse_pred_league_mean"] - res[f"rmse_{c}"]
        # Noise floor: RMSE a PERFECT predictor of true post-break talent would still have, because the
        # post-break rating itself is measured with sampling error K*h_post (weights = post-break poss).
        res["noise_floor"] = float(np.sqrt(np.average(K_MAIN * rel.sampling_h(d.post_poss, d.post_opp_poss),
                                                      weights=d.post_poss)))
        return res

    results = {}
    for label, d in (("pre_ge_25", ev[(ev.poss >= 25) & (ev.opp_poss >= 25)]), ("pre_ge_1", ev)):
        ci = rel.cluster_bootstrap(d, ["season_id", "team_id"], metrics, n_boot=n_boot, seed=4)
        tab = pd.DataFrame({"predictor": list(preds.values()),
                            "w_rmse": [ci.loc[f"rmse_{c}", "estimate"] for c in preds],
                            "rmse_gain_vs_raw": [ci.loc[f"gain_{c}", "estimate"] for c in preds],
                            "gain_lo": [ci.loc[f"gain_{c}", "lo"] for c in preds],
                            "gain_hi": [ci.loc[f"gain_{c}", "hi"] for c in preds],
                            "gain_vs_league_mean": [ci.loc[f"gain_vs_mean_{c}", "estimate"] for c in preds],
                            "gvm_lo": [ci.loc[f"gain_vs_mean_{c}", "lo"] for c in preds],
                            "gvm_hi": [ci.loc[f"gain_vs_mean_{c}", "hi"] for c in preds],
                            "calibration_slope": [ci.loc[f"slope_{c}", "estimate"] for c in preds],
                            "slope_lo": [ci.loc[f"slope_{c}", "lo"] for c in preds],
                            "slope_hi": [ci.loc[f"slope_{c}", "hi"] for c in preds]})
        print(f"-- population: {label} (n = {len(d):,} lineups, post-break >= 25 poss, weights = post-break poss)")
        print(tab.round(3).to_string(index=False))
        floor = ci.loc["noise_floor", "estimate"]
        print(f"   noise floor of the post-break target (sampling error alone): RMSE {floor:.2f}")
        mse_mean = ci.loc["rmse_pred_league_mean", "estimate"] ** 2
        r2_ceiling = 1 - floor**2 / mse_mean
        r2_best = 1 - ci.loc["rmse_pred_eb_team", "estimate"] ** 2 / mse_mean
        print(f"   R^2 ceiling vs league mean (perfect knowledge of true talent): {r2_ceiling:.3f}; "
              f"EB → team prior achieves {r2_best:.3f} ({r2_best / r2_ceiling:.0%} of the explainable variance)")
        results[label] = {"n": len(d), "eff_n": rel.kish_effective_n(d.post_poss), "noise_floor_rmse": floor,
                          "r2_ceiling_vs_league_mean": r2_ceiling, "r2_eb_team_vs_league_mean": r2_best,
                          "table": tab.round(3).to_dict("records")}
    F["shrinkage_evaluation"] = results

    # fig08: raw vs shrunk (left) and the RMSE comparison (right)
    d = ev[(ev.poss >= 25) & (ev.opp_poss >= 25)]
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.8), gridspec_kw={"width_ratios": [1, 1.15]})
    sc = ax[0].scatter(d.net_rating, d.pred_eb_league, c=np.log10(d.poss), cmap="Blues", vmin=1.0, vmax=3.2,
                       s=12, linewidths=0)
    ax[0].plot([-60, 60], [-60, 60], color=MUTED, lw=1, ls="--", label="No shrinkage (y = x)")
    ax[0].set(xlim=(-60, 60), ylim=(-60, 60), xlabel="Raw pre-break net rating",
              ylabel="EB-shrunk estimate", title="Small samples are pulled hard toward the mean")
    cb = fig.colorbar(sc, ax=ax[0], fraction=0.045)
    cb.set_label("Pre-break possessions", color=INK_2)
    cb.set_ticks([1, 2, 3])
    cb.set_ticklabels(["10", "100", "1,000"])
    ax[0].legend(loc="upper left", fontsize=8)
    tab = pd.DataFrame(results["pre_ge_25"]["table"])
    yy = np.arange(len(tab))[::-1]
    ax[1].barh(yy, tab.w_rmse, color=[MUTED if p.startswith(("Raw", "League")) else BLUE for p in tab.predictor],
               height=0.6)
    for yv, v in zip(yy, tab.w_rmse):
        ax[1].annotate(f"{v:.1f}", (v, yv), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8.5)
    ax[1].set(yticks=yy, xlabel="Possession-weighted RMSE vs post-break net rating (lower is better)",
              title=f"Predicting the post-break rating (n = {len(d):,} lineups)")
    ax[1].set_yticklabels(tab.predictor)
    ax[1].set_xlim(0, tab.w_rmse.max() * 1.15)
    ax[1].grid(axis="y", visible=False)
    save(fig, FIG / "fig08_shrinkage.png")
    return ev


# ---------------------------------------------------------------------------------------------------- 7
def regression_to_mean(ev: pd.DataFrame) -> None:
    heading("7a. Regression to the mean among lineups that continue (pre >= 25, post >= 25)")
    d = ev[(ev.poss >= 25) & (ev.opp_poss >= 25)].copy()
    w = d.post_poss
    out = {"n": len(d),
           "pre_raw_mean": wavg(d.net_rating, w), "pre_eb_mean": wavg(d.pred_eb_league, w),
           "post_mean": wavg(d.post_net_rating, w),
           "slope_post_on_raw": wslope(d.net_rating, d.post_net_rating, w),
           "slope_post_on_eb": wslope(d.pred_eb_league, d.post_net_rating, w)}
    print({k: round(v, 3) for k, v in out.items()})

    # Stability of TRUE quality across the break (Spearman's correction for attenuation). Pre and post windows
    # share no possessions, so Cov(x_pre, x_post) = Cov(true_pre, true_post); dividing by the signal SDs
    # (observed variance minus mean sampling variance) gives the correlation of the true ratings.
    def stability(b: pd.DataFrame) -> dict[str, float]:
        hp, hq = rel.sampling_h(b.poss, b.opp_poss), rel.sampling_h(b.post_poss, b.post_opp_poss)
        sig_pre = b.net_rating.var() - K_MAIN * hp.mean()
        sig_post = b.post_net_rating.var() - K_MAIN * hq.mean()
        cov = np.cov(b.net_rating, b.post_net_rating)[0, 1]
        return {"observed_r": float(np.corrcoef(b.net_rating, b.post_net_rating)[0, 1]),
                "true_r": float(cov / np.sqrt(max(sig_pre, 1e-9) * max(sig_post, 1e-9))),
                "signal_var_pre": float(sig_pre), "signal_var_post": float(sig_post), "cov": float(cov)}

    ci = rel.cluster_bootstrap(d, ["season_id", "team_id"], stability, n_boot=N_BOOT, seed=6)
    print(ci.round(3))
    out["stability"] = {k: {"estimate": float(r.estimate), "ci95": [float(r.lo), float(r.hi)]} for k, r in ci.iterrows()}
    F["regression_to_mean"] = out

    fig, ax = plt.subplots(figsize=(7.5, 5))
    for col, color, label in (("net_rating", ORANGE, "Raw pre-break rating"),
                              ("pred_eb_league", BLUE, "EB-shrunk pre-break rating")):
        d["bin"] = pd.qcut(d[col], 10, labels=False, duplicates="drop")
        g = d.groupby("bin")
        xs = g.apply(lambda b: wavg(b[col], b.post_poss))
        ys = g.apply(lambda b: wavg(b.post_net_rating, b.post_poss))
        ax.plot(xs, ys, "o-", color=color, ms=7, label=f"{label} (slope {wslope(d[col], d.post_net_rating, w):.2f})")
    ax.plot([-30, 30], [-30, 30], color=MUTED, lw=1, ls="--", label="y = x (no regression to the mean)")
    ax.set(xlim=(-30, 30), ylim=(-12, 12), xlabel="Pre-break estimate (decile means)",
           ylabel="Post-break net rating (possession-weighted mean)",
           title="Pre-break ratings over-predict: raw slope ≈ 0.1, shrunk ≈ 0.4 (1 = calibrated)")
    ax.legend(fontsize=8, loc="upper left")
    save(fig, FIG / "fig09_regression_to_mean.png")


def selection(lw: pd.DataFrame, pre: pd.DataFrame, players: pd.DataFrame, vc: rel.VarianceComponents,
              n_boot: int) -> None:
    heading("7b. Selection: which pre-break lineups continue after the break?")
    X = cont.build_features(pre, players, vc)
    y = cont.labels(lw, X.index)
    F["continuation_population"] = {"n": len(X), "appears_rate": float(y.appears.mean()),
                                    "continues_rate": float(y.continues.mean()),
                                    "definition": f"pre >= {cont.MIN_PRE_POSS} poss each end; continues = post >= "
                                                  f"{cont.MIN_POST_POSS} poss"}
    print(F["continuation_population"])

    # Who continues? Rates by pre-break possessions (bins) and by quality (EB quintiles)
    X2 = X.join(y)
    X2["poss_bin"] = pd.cut(X2.poss, [25, 50, 100, 200, 400, 10_000], right=False)
    by_poss = X2.groupby("poss_bin", observed=True)[["appears", "continues"]].mean().assign(n=X2.groupby("poss_bin", observed=True).size())
    X2["eb_q"] = pd.qcut(X2.eb_net, 5, labels=["Q1 (worst)", "Q2", "Q3", "Q4", "Q5 (best)"])
    by_q = X2.groupby("eb_q", observed=True)[["appears", "continues"]].mean()
    print(by_poss.round(3)); print(by_q.round(3))
    F["continuation_by_possessions"] = by_poss.round(4).reset_index().astype({"poss_bin": str}).to_dict("records")
    F["continuation_by_quality_quintile"] = by_q.round(4).reset_index().astype({"eb_q": str}).to_dict("records")

    cv = {k: cont.cross_validate(X, y.continues, k) for k in ("loso", "forward")}
    for k, r in cv.items():
        print(f"-- CV scheme: {k}"); print(r.folds.round(3).to_string(index=False))
    F["continuation_cv"] = {k: r.folds.round(4).to_dict("records") for k, r in cv.items()}
    p = cv["loso"].predictions
    pooled = {"auc": float(cont.roc_auc_score(y.continues, p)), "brier": float(cont.brier_score_loss(y.continues, p)),
              "brier_base_rate": float(cont.brier_score_loss(y.continues, np.full(len(p), y.continues.mean())))}
    F["continuation_cv_pooled_loso"] = pooled
    print("pooled LOSO:", {k: round(v, 4) for k, v in pooled.items()})

    nonirr = ~X.season_id.isin(IRREGULAR_SEASONS)
    r_reg = cont.cross_validate(X[nonirr], y.continues[nonirr], "loso")
    F["continuation_cv_excluding_irregular"] = {"mean_auc": float(r_reg.folds.auc.mean()),
                                                "mean_auc_all_seasons": float(cv["loso"].folds.auc.mean())}

    ors = cont.odds_ratios(X, y.continues, n_boot=n_boot, seed=5)
    print(ors.round(3))
    F["continuation_odds_ratios_per_sd"] = {k: {"or": float(r.odds_ratio), "ci95": [float(r.lo), float(r.hi)],
                                                "feature_sd": float(X[k].std())} for k, r in ors.iterrows()}
    cal = cont.calibration_table(p, y.continues)
    F["continuation_calibration"] = cal.round(4).to_dict("records")

    # Impact on the modeling sample
    sel = y.continues == 1
    ipw = 1 / p
    ipw_trim = 1 / p.clip(lower=0.05)   # trimming: caps any weight at 20 (bias-variance trade-off)
    bal = pd.DataFrame({
        "feature": cont.FEATURES,
        "mean_all_eligible": [X[f].mean() for f in cont.FEATURES],
        "mean_continuers": [X.loc[sel, f].mean() for f in cont.FEATURES],
        "smd_unweighted": [cont.standardized_mean_difference(X[f], y.continues) for f in cont.FEATURES],
        "smd_ipw": [cont.standardized_mean_difference(X[f], y.continues, ipw) for f in cont.FEATURES],
        "smd_ipw_trimmed": [cont.standardized_mean_difference(X[f], y.continues, ipw_trim) for f in cont.FEATURES]})
    print(bal.round(3).to_string(index=False))
    F["selection_balance"] = bal.round(4).to_dict("records")
    F["ipw_effective_n_continuers"] = {"n": int(sel.sum()), "kish_eff_n": rel.kish_effective_n(ipw[sel]),
                                       "kish_eff_n_trimmed": rel.kish_effective_n(ipw_trim[sel]),
                                       "max_weight": float(ipw[sel].max()), "min_p_continuer": float(p[sel].min())}
    print(F["ipw_effective_n_continuers"])

    # Composition of the Phase 5/6 modeling sample: how many target lineups have their own pre-break history?
    postlw = lw[(lw.window_type == "post_asb") & (lw.poss >= 25) & (lw.opp_poss >= 25)]
    pre_poss = pre.set_index("lineup_id").poss
    hist = postlw.lineup_id.map(pre_poss).fillna(0)
    comp = pd.cut(hist, [-1, 0, 24, 99, 10_000], labels=["0 (new after the break)", "1–24", "25–99", "100+"])
    comp_tab = pd.DataFrame({"lineups": comp.value_counts(sort=False),
                             "share_of_post_poss": postlw.poss.groupby(comp.values, observed=False).sum()
                             / postlw.poss.sum()})
    print("modeling-sample composition by own pre-break possessions:"); print(comp_tab.round(3))
    F["modeling_sample_pre_break_history"] = comp_tab.round(4).reset_index(names="pre_break_poss").astype(
        {"pre_break_poss": str}).to_dict("records")

    # fig10: who continues + calibration + odds ratios
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6), gridspec_kw={"width_ratios": [1, 0.85, 1.2]})
    xb = np.arange(len(by_poss))
    ax[0].plot(xb, by_poss.appears, "o-", color=AQUA, ms=7, label="Appears after the break (any possession)")
    ax[0].plot(xb, by_poss.continues, "s-", color=BLUE, ms=7, label="Continues (≥ 25 post-break possessions)")
    ax[0].set(xticks=xb, ylim=(0, 1), xlabel="Pre-break possessions", ylabel="Share of lineups",
              title="Heavily used lineups keep playing")
    ax[0].set_xticklabels([str(b).replace(", ", "–").strip("[)").replace("–10000", "+") for b in by_poss.index])
    ax[0].legend(fontsize=8, loc="upper left")
    ax[1].plot([0, 1], [0, 1], color=MUTED, lw=1, ls="--", label="Perfect calibration")
    ax[1].plot(cal.mean_predicted, cal.observed_rate, "o-", color=BLUE, ms=7, label="Deciles (out-of-season)")
    lim = max(cal.mean_predicted.max(), cal.observed_rate.max()) * 1.08
    ax[1].set(xlim=(0, lim), ylim=(0, lim), xlabel="Predicted P(continue)", ylabel="Observed rate",
              title=f"Calibration (LOSO AUC {pooled['auc']:.2f})")
    ax[1].legend(fontsize=8, loc="upper left")
    o = ors.iloc[::-1]
    yy = np.arange(len(o))
    ax[2].errorbar(o.odds_ratio, yy, xerr=[o.odds_ratio - o.lo, o.hi - o.odds_ratio], fmt="o", color=BLUE,
                   ms=7, capsize=3)
    ax[2].axvline(1, color=MUTED, lw=1)
    ax[2].set_xscale("log")
    ticks = [0.5, 0.75, 1, 1.5, 2]
    ax[2].set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax[2].xaxis.set_minor_locator(plt.NullLocator())
    ax[2].set(yticks=yy, xlabel="Odds ratio per 1 SD (log scale, 95% cluster-bootstrap CI)",
              title="What predicts continuation?")
    ax[2].set_yticklabels([cont.FEATURE_LABELS[f] for f in o.index], fontsize=8.5)
    ax[2].grid(axis="y", visible=False)
    save(fig, FIG / "fig10_continuation_model.png")

    # fig11: selection shifts the modeling sample
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
    edges = np.linspace(-6, 10, 41)
    ax[0].hist(X.eb_net[~sel], bins=edges, density=True, histtype="step", lw=2, color=MUTED,
               label=f"Do not continue (n = {(~sel).sum():,})")
    ax[0].hist(X.eb_net[sel], bins=edges, density=True, histtype="step", lw=2, color=BLUE,
               label=f"Continue (n = {sel.sum():,})")
    ax[0].set(xlabel="EB-shrunk pre-break net rating", ylabel="Density",
              title="Continuing lineups were better before the break")
    ax[0].legend(fontsize=8, loc="upper left")
    ct = comp_tab.reset_index()
    ax[1].barh(np.arange(len(ct))[::-1], ct.share_of_post_poss * 100, color=BLUE, height=0.6)
    for yv, v, n in zip(np.arange(len(ct))[::-1], ct.share_of_post_poss * 100, ct.lineups):
        ax[1].annotate(f"{v:.0f}%  ({n:,} lineups)", (v, yv), xytext=(4, 0), textcoords="offset points",
                       va="center", fontsize=8.5)
    ax[1].set(yticks=np.arange(len(ct))[::-1], xlim=(0, 100),
              xlabel="Share of post-break possessions in the modeling sample (%)",
              title="Own pre-break history of lineups in the modeling sample")
    ax[1].set_yticklabels([f"{c} pre-break poss" for c in ct["index"]] if "index" in ct else ct.iloc[:, 0])
    ax[1].grid(axis="y", visible=False)
    save(fig, FIG / "fig11_selection_impact.png")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=300, help="bootstrap replicates")
    args = ap.parse_args()
    apply_style()
    pd.set_option("display.width", 200)
    OUT.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        lw = data.lineup_windows(c)
        splits = data.location_splits(c)
        games = data.team_games(c)
        players = data.pre_break_lineup_players(c)
    pre = lw[lw.window_type == "pre_asb"].copy()
    F["rows_read"] = {"lineup_windows": len(lw), "pre_break": len(pre), "split_lineups": len(splits),
                      "team_games": len(games)}

    distributions(lw)
    vc = measurement_model(pre, args.boot)
    global K_MAIN, N_BOOT
    K_MAIN, N_BOOT = vc.k, args.boot
    reliability_curve(pre, vc, args.boot)
    split_half_analysis(splits, pre, vc, games, args.boot)
    uncertainty_examples(vc)
    ev = shrinkage(lw, pre, args.boot)
    regression_to_mean(ev)
    selection(lw, pre, players, vc, args.boot)

    (OUT / "findings.json").write_text(json.dumps(F, indent=1, default=float) + "\n")
    print(f"\nwrote {OUT / 'findings.json'} and {len(list(FIG.glob('*.png')))} figures in {FIG}")


if __name__ == "__main__":
    main()
