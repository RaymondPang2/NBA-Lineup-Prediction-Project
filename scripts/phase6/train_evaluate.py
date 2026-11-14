"""Phase 6 (development): nested chronological CV of linear regression, ridge and random forest against the
Phase 5 baselines; interpretability; pre-registered model selection; final fit; FREEZE.

Reads development seasons only (2018-19 .. 2023-24). The held-out seasons are not read here; they can only
be read by scripts/phase6/holdout_evaluation.py after models/final/ is committed.

Writes:
    reports/phase6/*.csv, reports/phase6/findings_dev.json, reports/phase6/figures/fig16-fig21
    models/final/model.joblib, models/final/frozen_spec.json

Usage:  .venv/bin/python scripts/phase6/train_evaluate.py [--boot 1000]
"""
from __future__ import annotations

import argparse
import json
import time
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from nba_lineups.analysis.plotting import AQUA, BLUE, INK_2, MUTED, ORANGE, apply_style, save
from nba_lineups.config import DEV_SEASONS, HELDOUT_SEASONS, IRREGULAR_SEASONS, PROJECT_ROOT
from nba_lineups.db.connection import connect
from nba_lineups.modeling import baselines as bl
from nba_lineups.modeling import evaluation as ev
from nba_lineups.modeling import final, interpret, raw, tuning
from nba_lineups.modeling.models import FEATURES, MODEL_NAMES, SPECS, weighted_rmse
from nba_lineups.modeling.splits import VARIANTS, expanding_window_folds

warnings.filterwarnings("ignore", category=DeprecationWarning)
OUT = PROJECT_ROOT / "reports" / "phase6"
FIG = OUT / "figures"
MODEL_DIR = PROJECT_ROOT / "models" / "final"
REGULAR_VAL = [s for s in DEV_SEASONS[1:] if s not in IRREGULAR_SEASONS]
BASE = bl.PRIMARY                                  # league mean, team prior, calibrated, EB lineup, player composite
PRED = BASE + MODEL_NAMES
LABEL = {**bl.BASELINES, **{m: SPECS[m].label for m in MODEL_NAMES}}
MCOLOR = {"linear": BLUE, "ridge": ORANGE, "forest": AQUA}
F: dict = {"seasons": list(DEV_SEASONS), "held_out_never_read": list(HELDOUT_SEASONS)}


def heading(t: str) -> None:
    print(f"\n=== {t}", flush=True)


def summary(ci: pd.DataFrame, wt: str = "weighted") -> pd.DataFrame:
    keep = ["rmse", "mae", "r2", "rmse_minus_team_prior", "rmse_minus_league_mean"]
    d = ci[(ci.weighting == wt) & ci.metric.isin(keep)]
    d = d.assign(v=[f"{e:.3f} [{lo:.3f}, {hi:.3f}]" for e, lo, hi in zip(d.estimate, d.lo, d.hi)])
    return d.pivot_table(index="predictor", columns="metric", values="v", aggfunc="first").reindex(PRED + ["noise_floor"])


# ---------------------------------------------------------------------------------------------------- 1
def compare(runs: dict[str, tuning.ModelRun], n_boot: int) -> pd.DataFrame:
    heading("1. Pooled out-of-fold comparison (paired, team-season cluster bootstrap)")
    evals = {"all": runs["all"].oof, "all_regular_val": runs["all"].oof[runs["all"].oof.season_id.isin(REGULAR_VAL)],
             "regular_only": runs["regular_only"].oof}
    out = []
    for name, oof in evals.items():
        ci = ev.bootstrap_comparison(oof, PRED, MODEL_NAMES, BASE, n_boot=n_boot, seed=31)
        ci.insert(0, "evaluation", name)
        out.append(ci)
        print(f"-- {name}: n = {len(oof):,}, seasons {sorted(oof.season_id.unique())}")
        for wt in ("weighted", "unweighted"):
            print(f"   [{wt}]")
            print(summary(ci, wt).to_string())
    res = pd.concat(out, ignore_index=True)
    res.round(5).to_csv(OUT / "model_comparison.csv", index=False)
    F["comparison"] = {e: {f"{r.predictor}|{r.weighting}|{r.metric}": [round(r.estimate, 4), round(r.lo, 4), round(r.hi, 4)]
                           for r in res[res.evaluation == e].itertuples()} for e in evals}
    F["comparison_n"] = {e: {"n": len(d), "effective_n": float(d.w.sum() ** 2 / (d.w ** 2).sum())} for e, d in evals.items()}
    return res


def by_season_and_history(oof: pd.DataFrame, n_boot: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    heading("2. By validation season and by pre-break history (weighted; model minus team prior with 95% CI)")
    rows = []
    groups = [(f"season {s}", d) for s, d in oof.groupby("season_id")] + [
        ("no pre-break history", oof[oof.lu_no_history == 1]),
        ("history < 100 poss", oof[(oof.lu_no_history == 0) & (oof.lu_poss < 100)]),
        ("history >= 100 poss", oof[oof.lu_poss >= 100])]
    for label, d in groups:
        ci = ev.bootstrap_comparison(d, PRED, MODEL_NAMES, ["team_prior"], n_boot=n_boot, seed=41)
        for r in ci.itertuples():
            rows.append({"group": label, "n": len(d), "predictor": r.predictor, "weighting": r.weighting,
                         "metric": r.metric, "estimate": r.estimate, "lo": r.lo, "hi": r.hi})
    t = pd.DataFrame(rows)
    t.round(5).to_csv(OUT / "by_season_and_history.csv", index=False)
    w = t[t.weighting == "weighted"]
    show = w[w.metric.isin(["rmse"]) & w.predictor.isin(["league_mean", "team_prior"] + MODEL_NAMES)].pivot_table(
        index=["group"], columns="predictor", values="estimate").round(3)
    floor = w[(w.predictor == "noise_floor") & (w.metric == "rmse_floor")].set_index("group").estimate.round(3)
    show["noise_floor"] = floor
    print(show.to_string())
    d = w[w.metric == "rmse_minus_team_prior"]
    print((d.assign(v=[f"{e:+.3f} [{lo:+.3f}, {hi:+.3f}]" for e, lo, hi in zip(d.estimate, d.lo, d.hi)])
           .pivot_table(index="group", columns="predictor", values="v", aggfunc="first")).to_string())
    F["by_group_weighted"] = {f"{r.group}|{r.predictor}|{r.metric}": [round(r.estimate, 4), round(r.lo, 4), round(r.hi, 4)]
                              for r in w.itertuples() if r.metric in ("rmse", "r2", "rmse_minus_team_prior", "rmse_floor",
                                                                     "r2_ceiling", "skill_lm")}
    return t, show


# ---------------------------------------------------------------------------------------------------- 3
def interpretability(run: tuning.ModelRun) -> dict:
    heading("3. Interpretability (outer validation folds of the `all` variant)")
    coefs, selected, imp_single, imp_group = [], [], [], []
    single = {f: [f] for f in FEATURES}
    for (m, s), pipe in run.fitted.items():
        val = run.frames[s][1]
        if m in ("linear", "ridge"):
            c = interpret.coefficients(pipe)
            coefs.append(pd.DataFrame({"model": m, "val_season": s, "feature": c.index, "coef_per_sd": c.values}))
        if m == "linear":
            sel = pipe.named_steps["select"]
            selected.append({"val_season": s, "selected": sel.selected_, "dropped": [d for d, _ in sel.dropped_]})
        imp_single.append(interpret.permutation_importance(pipe, val, single, n_repeats=10, seed=1).assign(model=m, val_season=s))
        imp_group.append(interpret.permutation_importance(pipe, val, interpret.GROUPS, n_repeats=10, seed=2).assign(model=m, val_season=s))
    coefs, imp_single, imp_group = pd.concat(coefs), pd.concat(imp_single), pd.concat(imp_group)
    coefs.round(5).to_csv(OUT / "coefficients_by_fold.csv", index=False)
    imp_single.round(5).to_csv(OUT / "permutation_importance_by_fold.csv", index=False)
    imp_group.round(5).to_csv(OUT / "grouped_permutation_importance_by_fold.csv", index=False)
    sel_freq = pd.Series([f for r in selected for f in r["selected"]]).value_counts().reindex(FEATURES).fillna(0).astype(int)
    print("linear regression: folds (of 5) in which VIF pruning KEPT each feature:")
    print(sel_freq.to_string())
    cagg = coefs.groupby(["model", "feature"]).coef_per_sd.agg(["mean", "min", "max", "count"])
    print("standardized coefficients (net rating points per 1 SD), mean and range over folds:")
    print(cagg.round(3).to_string())
    gagg = imp_group.groupby(["model", "feature"]).rmse_increase.agg(["mean", "min", "max"]).round(4)
    print("grouped permutation importance (weighted RMSE increase on validation folds):")
    print(gagg.to_string())
    sagg = imp_single.groupby(["model", "feature"]).rmse_increase.mean().unstack(0).round(4)
    print("single-feature permutation importance (mean over folds):")
    print(sagg.sort_values("forest", ascending=False).to_string())
    F["interpretability"] = {"linear_vif_kept_folds": sel_freq.to_dict(), "linear_selection_by_fold": selected,
                             "coefficients": {f"{m}|{f}": [round(r["mean"], 4), round(r["min"], 4), round(r["max"], 4)]
                                              for (m, f), r in cagg.iterrows()},
                             "grouped_importance": {f"{m}|{f}": [r["mean"], r["min"], r["max"]] for (m, f), r in gagg.iterrows()},
                             "single_importance": sagg.to_dict()}
    plot_coefficients(coefs, sel_freq)
    plot_importance(imp_group, imp_single)
    return {"coefs": coefs, "imp_group": imp_group}


def diagnostics(run: tuning.ModelRun) -> None:
    heading("4. Calibration, residuals and overfitting")
    oof = run.oof
    cal = []
    for p in ["team_prior"] + MODEL_NAMES:
        b = ev.calibration_bins(oof.y, oof[p], oof.w).assign(predictor=p)
        cal.append(b)
    cal = pd.concat(cal)
    cal.round(4).to_csv(OUT / "calibration_bins.csv")
    slopes = {p: ev.calibration_slope(oof.y, oof[p], oof.w) for p in ["team_prior"] + MODEL_NAMES}
    sd_pred = {p: float(np.sqrt(np.average((oof[p] - np.average(oof[p], weights=oof.w)) ** 2, weights=oof.w)))
               for p in ["team_prior"] + MODEL_NAMES}
    print("weighted calibration slope (y on prediction):", {k: round(v, 3) for k, v in slopes.items()})
    print("weighted SD of predictions:", {k: round(v, 2) for k, v in sd_pred.items()})
    # Residuals vs the sampling noise of the target: z = residual / sqrt(K h_post). If the model captured all
    # predictable signal, the residual variance would be close to the sampling variance alone (z SD near 1).
    h = 1 / oof.post_poss + 1 / oof.post_opp_poss
    z = {p: (oof.y - oof[p]) / np.sqrt(oof.k * h) for p in ["team_prior"] + MODEL_NAMES}
    zsd = {p: float(np.sqrt(np.average(v ** 2, weights=oof.w))) for p, v in z.items()}
    inside = {p: float(np.average(np.abs(v) <= 1.96, weights=oof.w)) for p, v in z.items()}
    print("weighted RMS of residual / sampling SD:", {k: round(v, 3) for k, v in zsd.items()},
          "share inside +/-1.96 sampling SD:", {k: round(v, 3) for k, v in inside.items()})
    of = run.folds[["val_season", "model", "params", "tuned", "train_rmse_w", "val_rmse_w"]].copy()
    of["gap"] = of.val_rmse_w - of.train_rmse_w
    of.round(4).to_csv(OUT / "overfitting_by_fold.csv", index=False)
    print(of.round(3).to_string(index=False))
    gaps = of.groupby("model")[["train_rmse_w", "val_rmse_w", "gap"]].mean()
    print(gaps.round(3))
    F["diagnostics"] = {"calibration_slope_weighted": slopes, "prediction_sd_weighted": sd_pred,
                        "residual_over_sampling_sd_rms": zsd, "share_within_1.96_sampling_sd": inside,
                        "mean_train_val_gap": gaps.round(4).to_dict()}
    plot_calibration_residuals(cal, oof, z)
    plot_overfitting(of, run.curves)


# ---------------------------------------------------------------------------------------------------- figures
def plot_differences(res: pd.DataFrame) -> None:
    d = res[(res.evaluation == "all") & (res.metric == "rmse_minus_team_prior")]
    # Baselines vs the team prior come from the same bootstrap as "team prior minus baseline" gains: negate.
    g = res[(res.evaluation == "all") & (res.metric == "rmse_gain_tp") & res.predictor.isin(BASE)]
    g = g.assign(estimate=-g.estimate, lo=-g.hi, hi=-g.lo, metric="rmse_minus_team_prior")
    d = pd.concat([d, g])
    order = ["team_prior_calibrated", "eb_lineup_team", "player_composite"] + MODEL_NAMES
    floor = res[(res.evaluation == "all") & (res.predictor == "noise_floor") & (res.metric == "rmse_floor")]
    tp = res[(res.evaluation == "all") & (res.predictor == "team_prior") & (res.metric == "rmse")]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), sharey=True)
    for ax, wt in zip(axes, ("weighted", "unweighted")):
        r = d[d.weighting == wt].set_index("predictor").reindex(order)
        yy = np.arange(len(order))[::-1]
        colors = [MCOLOR.get(p, MUTED) for p in order]
        for yv, (e, lo_, hi_), col in zip(yy, r[["estimate", "lo", "hi"]].to_numpy(), colors):
            ax.errorbar([e], [yv], xerr=[[e - lo_], [hi_ - e]], fmt="o", color=col, ms=6, capsize=3, lw=1.6)
        ax.axvline(0, color=INK_2, lw=1)
        lim = float(floor[floor.weighting == wt].estimate.iloc[0] - tp[tp.weighting == wt].estimate.iloc[0])
        ax.axvline(lim, color=MUTED, ls="--", lw=1.2, label=f"Noise floor ({lim:+.2f}): best possible")
        for yv, e in zip(yy, r.estimate):
            ax.annotate(f"{e:+.3f}", (e, yv), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8, color=INK_2)
        ax.set(xlabel=f"RMSE minus team prior ({wt}); left of 0 = better", yticks=yy,
               title=f"{'Possession-weighted' if wt == 'weighted' else 'Unweighted'}: paired 95% CIs")
        ax.set_yticklabels([LABEL[p] for p in order])
        ax.grid(axis="y", visible=False)
        ax.legend(loc="lower left", fontsize=8)
    save(fig, FIG / "fig16_models_vs_team_prior.png",
         source="Nested expanding-window CV, validation 2019-20 to 2023-24 (n = 3,114 lineups). Team-season cluster bootstrap. "
                "NBA.com/stats via nba_api.")


def plot_by_season(t: pd.DataFrame) -> None:
    w = t[(t.weighting == "weighted") & t.group.str.startswith("season")]
    seasons = sorted(w.group.str.replace("season ", "").unique())
    x = np.arange(len(seasons))
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for p, c, mk in (("team_prior", MUTED, "o"), ("linear", BLUE, "s"), ("ridge", ORANGE, "^"), ("forest", AQUA, "D")):
        s = w[(w.predictor == p) & (w.metric == "skill_lm")].set_index("group").loc[[f"season {v}" for v in seasons]]
        ax.plot(x, s.estimate, color=c, marker=mk, ms=6, lw=1.8, label=LABEL[p])
    ceil = w[(w.predictor == "noise_floor") & (w.metric == "r2_ceiling")].set_index("group").loc[[f"season {v}" for v in seasons]]
    ax.plot(x, ceil.estimate, color=INK_2, ls="--", lw=1.2, marker="_", ms=14, label="R² ceiling (noise floor)")
    ax.axhline(0, color=MUTED, lw=0.8)
    n = w[(w.predictor == "team_prior") & (w.metric == "rmse")].set_index("group").n
    ax.set_xticks(x, [f"{s}{'*' if s in IRREGULAR_SEASONS else ''}\n(n = {n[f'season {s}']})" for s in seasons])
    ax.set(ylabel="Skill vs league mean (weighted)", xlabel="Validation season (* irregular)",
           title="Models track the team prior in every season, far below the ceiling")
    ax.legend(fontsize=8, ncols=3, loc="upper left")
    save(fig, FIG / "fig17_models_by_season.png")


def plot_coefficients(coefs: pd.DataFrame, sel_freq: pd.Series) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), sharey=True)
    order = coefs[coefs.model == "ridge"].groupby("feature").coef_per_sd.mean().sort_values().index.tolist()
    yy = np.arange(len(order))
    for ax, m in zip(axes, ("linear", "ridge")):
        g = coefs[coefs.model == m].groupby("feature").coef_per_sd.agg(["mean", "min", "max", "count"]).reindex(order)
        ok = g["count"].notna()
        ax.hlines(yy[ok], g["min"][ok], g["max"][ok], color=MCOLOR[m], alpha=0.35, lw=4, label="Range over the 5 outer folds")
        ax.plot(g["mean"][ok], yy[ok], "o", color=MCOLOR[m], ms=6, label="Mean over folds")
        ax.axvline(0, color=MUTED, lw=0.8)
        ax.set(xlabel="Coefficient: net-rating points per 1 SD of the feature", title=LABEL[m])
        ax.grid(axis="y", visible=False)
        ax.legend(loc="lower right", fontsize=8)
    axes[0].set_yticks(yy, [f"{f}  ({sel_freq[f]}/5)" if sel_freq[f] < 5 else f for f in order])
    axes[0].annotate("(k/5) = folds in which VIF pruning kept the feature; absent = never kept",
                     (0, -0.12), xycoords="axes fraction", fontsize=8, color=INK_2)
    save(fig, FIG / "fig18_coefficients.png")


def plot_importance(imp_group: pd.DataFrame, imp_single: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1, 1.1]})
    g = imp_group.groupby(["feature", "model"]).rmse_increase.mean().unstack()[MODEL_NAMES]
    g = g.loc[g.mean(axis=1).sort_values().index]
    yy = np.arange(len(g))
    hgt = 0.26
    for i, m in enumerate(MODEL_NAMES):
        axes[0].barh(yy + (i - 1) * hgt, g[m], height=hgt, color=MCOLOR[m], label=LABEL[m])
    axes[0].set_yticks(yy, g.index)
    axes[0].axvline(0, color=MUTED, lw=0.8)
    axes[0].set(xlabel="Weighted RMSE increase when the group is shuffled", title="Grouped permutation importance")
    axes[0].legend(fontsize=8, loc="lower right")
    axes[0].grid(axis="y", visible=False)
    s = imp_single[imp_single.model == "forest"].groupby("feature").rmse_increase.agg(["mean", "min", "max"]).sort_values("mean")
    y2 = np.arange(len(s))
    axes[1].hlines(y2, s["min"], s["max"], color=AQUA, alpha=0.35, lw=4, label="Range over folds")
    axes[1].plot(s["mean"], y2, "o", color=AQUA, ms=6, label="Mean over folds")
    axes[1].axvline(0, color=MUTED, lw=0.8)
    axes[1].set_yticks(y2, s.index)
    axes[1].set(xlabel="Weighted RMSE increase (validation folds)", title="Random forest: single-feature permutation importance")
    axes[1].legend(fontsize=8, loc="lower right")
    axes[1].grid(axis="y", visible=False)
    save(fig, FIG / "fig19_permutation_importance.png")


def plot_calibration_residuals(cal: pd.DataFrame, oof: pd.DataFrame, z: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))
    ax = axes[0]
    for p, c, mk in (("team_prior", MUTED, "o"), ("linear", BLUE, "s"), ("ridge", ORANGE, "^"), ("forest", AQUA, "D")):
        b = cal[cal.predictor == p]
        ax.errorbar(b.mean_pred, b.mean_y, yerr=1.96 * b.se_y if p == "linear" else None, color=c, marker=mk, ms=5,
                    lw=1.4, capsize=2, label=LABEL[p])
    lo, hi = cal.mean_pred.min() - 1, cal.mean_pred.max() + 1
    ax.plot([lo, hi], [lo, hi], color=INK_2, ls="--", lw=1, label="Perfect calibration")
    ax.set(xlabel="Mean prediction (decile of predictions, weighted)", ylabel="Mean post-break net rating (weighted)",
           title="Calibration by prediction decile (95% CI shown for linear)")
    ax.legend(fontsize=8, loc="upper left")
    ax = axes[1]
    m = "linear"
    res = oof.y - oof[m]
    ax.scatter(oof.post_poss, res, s=6, color=BLUE, alpha=0.35, linewidths=0, label=f"Residual, {LABEL[m]}")
    pp = np.geomspace(25, oof.post_poss.max(), 100)
    band = 1.96 * np.sqrt(oof.k.mean() * 2 / pp)
    ax.plot(pp, band, color=ORANGE, lw=1.6, label="±1.96 × sampling SD of the target")
    ax.plot(pp, -band, color=ORANGE, lw=1.6)
    ax.set_xscale("log")
    ax.set(xlabel="Post-break possessions (log scale)", ylabel="Residual (actual − predicted)",
           title=f"Residuals are mostly target noise ({np.average(np.abs(z[m]) <= 1.96, weights=oof.w):.0%} inside the band, weighted)")
    ax.set_ylim(-150, 150)
    ax.legend(fontsize=8, loc="upper right")
    save(fig, FIG / "fig20_calibration_residuals.png")


def plot_overfitting(of: pd.DataFrame, curves: list[pd.DataFrame]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
    ax = axes[0]
    seasons = sorted(of.val_season.unique())
    x = np.arange(len(seasons))
    for i, m in enumerate(MODEL_NAMES):
        d = of[of.model == m].set_index("val_season").loc[seasons]
        ax.plot(x + (i - 1) * 0.08, d.train_rmse_w, color=MCOLOR[m], marker="o", ls=":", ms=5, lw=1.2)
        ax.plot(x + (i - 1) * 0.08, d.val_rmse_w, color=MCOLOR[m], marker="s", ls="-", ms=5, lw=1.8, label=LABEL[m])
    ax.set_xticks(x, seasons)
    ax.set(xlabel="Outer validation season", ylabel="Weighted RMSE", title="Training (dotted) vs validation (solid) error")
    ax.legend(fontsize=8)
    ax = axes[1]
    rc = [c for c in curves if (c.model == "ridge").all()]
    for c, col in zip(rc, [MUTED, BLUE, ORANGE, AQUA, INK_2]):
        ax.plot(c.alpha, c.weighted_rmse - c.weighted_rmse.min(), marker="o", ms=3, lw=1.4, color=col,
                label=f"Outer val {c.outer_val_season.iloc[0]} (inner folds: {c.inner_folds.iloc[0]})")
    ax.set_xscale("log")
    ax.set(xlabel="Ridge alpha (log scale)", ylabel="Inner-CV weighted RMSE minus its minimum",
           title="Ridge tuning: flat up to alpha ~ 1,000 unless 2019-20 is the only inner validation season")
    ax.legend(fontsize=8)
    save(fig, FIG / "fig21_overfitting_and_tuning.png")


# ---------------------------------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=1000)
    args = ap.parse_args()
    apply_style()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_colwidth", 60)
    FIG.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with connect() as c:
        tables = raw.load_pre_break_tables(c, DEV_SEASONS)
        targets = raw.load_targets(c, DEV_SEASONS)
    cache = tuning.FoldCache(tables, targets)
    runs = {v: tuning.run_models(cache, expanding_window_folds(**kw), v) for v, kw in VARIANTS.items()}
    print(f"nested CV done in {time.time() - t0:.0f} s")
    folds = pd.concat([r.folds for r in runs.values()])
    folds.assign(params=folds.params.astype(str)).round(4).to_csv(OUT / "chosen_hyperparameters_by_fold.csv", index=False)
    pd.concat([c for r in runs.values() for c in r.curves]).round(5).to_csv(OUT / "tuning_curves.csv", index=False)
    print(folds.assign(params=folds.params.astype(str))[["variant", "val_season", "model", "params"]].to_string(index=False))
    F["hyperparameters_by_fold"] = folds.assign(params=folds.params.astype(str))[
        ["variant", "val_season", "model", "params", "tuned"]].to_dict("records")

    res = compare(runs, args.boot)
    t, _ = by_season_and_history(runs["all"].oof, max(300, args.boot // 2))
    interpretability(runs["all"])
    diagnostics(runs["all"])
    plot_differences(res)
    plot_by_season(t)

    heading("5. Pre-registered selection, final hyperparameters, final fit, FREEZE")
    sel = final.select_model(runs["all"].oof, n_boot=args.boot)
    print(sel)
    spec = SPECS[sel["chosen"]]
    params, curve = tuning.tune(spec, cache, tuple(DEV_SEASONS))
    print("final hyperparameters (chronological CV over all development seasons):", params)
    model = final.fit_final(sel["chosen"], params, tables, targets)
    cv_summary = {k: F["comparison"]["all"][k] for k in F["comparison"]["all"]
                  if k.split("|")[0] in (["team_prior", "league_mean", sel["chosen"], "noise_floor"])
                  and k.split("|")[2] in ("rmse", "mae", "r2", "rmse_minus_team_prior", "rmse_floor", "r2_ceiling")}
    frozen = final.freeze(model, MODEL_DIR, sel, cv_summary)
    print("frozen:", frozen["model"], frozen["artifact"])
    F["selection"] = sel | {"final_params": params,
                            "final_tuning_curve": None if curve is None else curve.round(4).to_dict("records")}
    F["frozen_artifact"] = frozen["artifact"]
    (OUT / "findings_dev.json").write_text(json.dumps(F, indent=1, default=float) + "\n")
    print(f"\nwrote reports/phase6 and models/final in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
