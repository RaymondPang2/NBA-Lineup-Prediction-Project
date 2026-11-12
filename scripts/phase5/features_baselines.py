"""Phase 5: feature quality, chronological cross-validation of baselines, noise floor (development seasons only).

Reads the loaded database (read-only) and writes:
    reports/phase5/feature_dictionary.csv    every feature: group, description, source, fitted parameters, availability
    reports/phase5/feature_quality.csv       coverage, distribution, season drift, collinearity, target correlation
    reports/phase5/baseline_metrics.csv      pooled out-of-fold metrics with team-season cluster-bootstrap 95% CIs
    reports/phase5/baseline_per_fold.csv     the same metrics per validation season
    reports/phase5/fold_parameters.csv       fitted hyperparameters of every fold (stability check)
    reports/phase5/findings.json             every number quoted in docs/features_baselines.md
    reports/phase5/figures/*.png

Only 2018-19 .. 2023-24 are read (nba_lineups.modeling.raw enforces it). 2024-25 and 2025-26 stay held out.
No Phase 6 model (linear regression, ridge, random forest) is trained here.

Usage:  .venv/bin/python scripts/phase5/features_baselines.py [--boot 1000]
"""
from __future__ import annotations

import argparse
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from nba_lineups.analysis import reliability as rel
from nba_lineups.analysis.plotting import BLUE, INK_2, MUTED, ORANGE, apply_style, save
from nba_lineups.config import DEV_SEASONS, HELDOUT_SEASONS, IRREGULAR_SEASONS, PROJECT_ROOT
from nba_lineups.db.connection import connect
from nba_lineups.modeling import baselines as bl
from nba_lineups.modeling import cv, raw, registry
from nba_lineups.modeling import evaluation as ev
from nba_lineups.modeling.features import FeatureBuilder
from nba_lineups.modeling.registry import FEATURE_NAMES
from nba_lineups.modeling.splits import VARIANTS, expanding_window_folds

OUT = PROJECT_ROOT / "reports" / "phase5"
FIG = OUT / "figures"
REGULAR_VAL = [s for s in DEV_SEASONS[1:] if s not in IRREGULAR_SEASONS]
F: dict = {"seasons": list(DEV_SEASONS), "held_out_never_read": list(HELDOUT_SEASONS)}


def heading(t: str) -> None:
    print(f"\n=== {t}")


# ---------------------------------------------------------------------------------------------------- 1
def sample(targets: pd.DataFrame, full: pd.DataFrame) -> None:
    heading("1. Modeling sample (post-break >= 25 possessions on each end)")
    g = full.groupby("season_id")
    tab = pd.DataFrame({"lineups": g.size(), "effective_n": g.w.apply(rel.kish_effective_n),
                        "no_history_share": g.lu_no_history.mean(),
                        "no_history_poss_share": g.apply(lambda d: np.average(d.lu_no_history, weights=d.w)),
                        "weighted_mean_y": g.apply(lambda d: np.average(d.y, weights=d.w))})
    print(tab.round(3))
    F["sample"] = {"n": len(targets), "effective_n": rel.kish_effective_n(targets.w),
                   "no_history_share": float(full.lu_no_history.mean()),
                   "no_history_possession_share": float(np.average(full.lu_no_history, weights=full.w)),
                   "by_season": tab.round(4).reset_index().to_dict("records")}


# ---------------------------------------------------------------------------------------------------- 2
def vif(x: pd.DataFrame) -> pd.Series:
    """Variance inflation factor: diagonal of the inverse correlation matrix (1 = uncorrelated with the rest)."""
    c = np.corrcoef(x.to_numpy(float), rowvar=False)
    return pd.Series(np.diag(np.linalg.pinv(c)), index=x.columns)


def feature_quality(full: pd.DataFrame, tables: raw.PreBreakTables) -> pd.DataFrame:
    heading("2. Feature quality (builder fitted on all development seasons; descriptive only, nothing selected)")
    X = full[list(FEATURE_NAMES)]
    # How often a feature is backed by real pre-break data rather than a prior / fallback value.
    observed = {
        "lu_net_eb_team": 1 - full.lu_no_history, "lu_log_poss": 1 - full.lu_no_history,
        "lu_no_history": pd.Series(1, index=full.index), "lu_pair_familiarity": (full.lu_pair_familiarity > 0).astype(int)}
    player_obs = (5 - full.p_n_no_history) / 5
    for f in FEATURE_NAMES:
        observed.setdefault(f, player_obs if f.startswith("p_") else pd.Series(1, index=full.index))
    q = pd.DataFrame({
        "group": [s.group for s in registry.FEATURES],
        "observed_share": [float(observed[f].mean()) for f in FEATURE_NAMES],
        "mean": X.mean(), "sd": X.std(), "min": X.min(), "median": X.median(), "max": X.max(),
        "season_mean_range": X.groupby(full.season_id).mean().agg(lambda s: s.max() - s.min()),
        "vif": vif(X)}, index=list(FEATURE_NAMES))
    q["season_drift_sd_units"] = q.season_mean_range / q.sd
    # Weighted correlation with the target: pooled, and the range across seasons (sign stability).
    q["corr_y_weighted"] = [ev.weighted_corr(full[f], full.y, full.w) for f in FEATURE_NAMES]
    by_season = pd.DataFrame({s: [ev.weighted_corr(d[f], d.y, d.w) if d[f].std() > 0 else np.nan
                                  for f in FEATURE_NAMES] for s, d in full.groupby("season_id")},
                             index=list(FEATURE_NAMES))
    q["corr_y_season_min"], q["corr_y_season_max"] = by_season.min(axis=1), by_season.max(axis=1)
    q["corr_y_sign_consistent"] = (np.sign(by_season).nunique(axis=1) == 1)
    q.index.name = "feature"
    print(q.round(3).to_string())

    corr = X.corr()
    high = [(a, b, round(float(corr.loc[a, b]), 3)) for i, a in enumerate(X.columns) for b in X.columns[i + 1:]
            if abs(corr.loc[a, b]) >= 0.8]
    print("feature pairs with |r| >= 0.8:", high)

    # Source check for usage: the player endpoint's pre-break possessions vs on-court lineup possessions.
    # Equal up to the known ~3% feed difference => the endpoint's STATS respect the date window (its team
    # label does not, which is why it's never used).
    on = tables.player_team.groupby(["season_id", "player_id"]).on_poss.sum()
    nteams = tables.player_team.groupby(["season_id", "player_id"]).size()
    u = tables.usage.set_index(["season_id", "player_id"]).join(on.rename("on_poss")).join(nteams.rename("n_teams"))
    u = u[u.on_poss >= 500]
    ratio = u.usage_poss / u.on_poss
    traded = ratio[u.n_teams >= 2]
    usage_check = {"players_ge_500_poss": int(len(u)), "ratio_median": float(ratio.median()),
                   "ratio_p01_p99": [float(ratio.quantile(.01)), float(ratio.quantile(.99))],
                   "traded_players": int(len(traded)), "traded_ratio_min_max": [float(traded.min()), float(traded.max())]}
    print("usage source check:", {k: np.round(v, 4) if isinstance(v, float) else v for k, v in usage_check.items()})

    F["feature_quality"] = {"high_correlation_pairs": high, "usage_source_check": usage_check,
                            "max_vif": float(q.vif.max()), "n_features": len(FEATURE_NAMES)}
    q.round(5).to_csv(OUT / "feature_quality.csv")
    corr.round(4).to_csv(OUT / "feature_correlation.csv")
    plot_feature_target(q)
    plot_feature_corr(corr)
    return q


# ---------------------------------------------------------------------------------------------------- 3
def baselines(tables: raw.PreBreakTables, targets: pd.DataFrame, n_boot: int) -> dict:
    heading("3. Baselines, expanding-window cross-validation")
    preds = list(bl.BASELINES)
    runs = {v: cv.run_baselines(tables, targets, expanding_window_folds(**kw), v) for v, kw in VARIANTS.items()}
    evals = {"all": runs["all"].oof, "all_regular_val": runs["all"].restrict(REGULAR_VAL),
             "regular_only": runs["regular_only"].oof}
    tables_out, per_fold, params = [], [], []
    for name, oof in evals.items():
        ci = ev.bootstrap_metrics(oof, preds, n_boot=n_boot, seed=11)
        ci.insert(0, "evaluation", name)
        tables_out.append(ci)
        pf = ev.per_fold(oof, preds)
        pf.insert(0, "evaluation", name)
        per_fold.append(pf)
        print(f"-- {name}: {len(oof):,} validation lineups, seasons {sorted(oof.season_id.unique())}, "
              f"effective n {rel.kish_effective_n(oof.w):.0f}")
        show = ci[ci.metric.isin(["rmse", "mae", "r2", "skill_lm", "rmse_gain_tp"])]
        print(show.pivot_table(index=["weighting", "predictor"], columns="metric", values="estimate").round(3))
    for v, run in runs.items():
        for p in run.params:
            row = {"variant": v, "val_season": p["val_season"], "n_train": p["n_train"], "n_val": p["n_val"]}
            for block, vals in p["features"].items():
                if isinstance(vals, dict):
                    row |= {f"{block}.{k}": v2 for k, v2 in vals.items()}
            row |= {"baseline.league_mean": p["baselines"]["league_mean"],
                    "baseline.team_prior_offset": p["baselines"]["team_prior_offset"],
                    "baseline.eb_offset": p["baselines"]["eb_lineup_team_offset"],
                    "baseline.player_offset": p["baselines"]["player_composite_offset"],
                    "baseline.calibrated_slope": p["baselines"]["team_prior_calibrated"]["slope"]}
            params.append(row)
    metrics = pd.concat(tables_out, ignore_index=True)
    metrics.round(5).to_csv(OUT / "baseline_metrics.csv", index=False)
    pf = pd.concat(per_fold, ignore_index=True)
    pf.round(5).to_csv(OUT / "baseline_per_fold.csv", index=False)
    fp = pd.DataFrame(params)
    fp.round(5).to_csv(OUT / "fold_parameters.csv", index=False)
    stab = fp[fp.variant == "all"][[c for c in fp.columns if c.endswith((".tau", ".k", "beta1_log_poss", "mu",
                                                                      "offset", "slope", "league_mean"))]]
    print("hyperparameter stability across 'all' folds (min / max):")
    print(stab.agg(["min", "max"]).T.round(3))

    F["baselines"] = {}
    for name in evals:
        m = metrics[metrics.evaluation == name]
        F["baselines"][name] = {
            "n": int(len(evals[name])), "effective_n": rel.kish_effective_n(evals[name].w),
            "val_seasons": sorted(evals[name].season_id.unique()),
            "metrics": {f"{r.predictor}|{r.weighting}|{r.metric}": [round(r.estimate, 4), round(r.lo, 4), round(r.hi, 4)]
                        for r in m.itertuples()}}
    F["fold_parameter_ranges_all"] = stab.agg(["min", "max"]).round(4).to_dict()
    subgroup(runs["all"].oof)
    plot_baselines(metrics[metrics.evaluation == "all"], len(evals["all"]))
    plot_folds(pf[pf.evaluation == "all"])
    return runs


def subgroup(oof: pd.DataFrame) -> None:
    heading("3b. Where does lineup history help? (all-seasons CV, weighted RMSE by subgroup)")
    rows = []
    for label, d in (("no pre-break history", oof[oof.lu_no_history == 1]),
                     ("history, < 100 poss", oof[(oof.lu_no_history == 0) & (oof.lu_poss < 100)]),
                     ("history, >= 100 poss", oof[oof.lu_poss >= 100])):
        r = {"subgroup": label, "n": len(d), "poss_share": d.w.sum() / oof.w.sum()}
        for p in bl.PRIMARY:
            r[p] = ev.regression_metrics(d.y, d[p], d.w)["rmse"]
        r["noise_floor"] = ev.noise_floor(d, d.w)["rmse_floor"]
        rows.append(r)
    t = pd.DataFrame(rows)
    print(t.round(3).to_string(index=False))
    F["subgroups_weighted_rmse"] = t.round(4).to_dict("records")


# ---------------------------------------------------------------------------------------------------- figures
def plot_baselines(m: pd.DataFrame, n: int) -> None:
    order = bl.PRIMARY
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.4), gridspec_kw={"width_ratios": [1.15, 1]})
    yy = np.arange(len(order))[::-1]
    for a, wt, color in ((ax[0], "weighted", BLUE),):
        r = m[(m.weighting == wt) & (m.metric == "rmse")].set_index("predictor").loc[order]
        a.errorbar(r.estimate, yy, xerr=[r.estimate - r.lo, r.hi - r.estimate], fmt="o", color=color, ms=6,
                   capsize=3, lw=1.5, label="Out-of-fold RMSE, 95% CI")
        fl = m[(m.predictor == "noise_floor") & (m.weighting == wt) & (m.metric == "rmse_floor")].iloc[0]
        a.axvspan(fl.lo, fl.hi, color=MUTED, alpha=0.18, lw=0)
        a.axvline(fl.estimate, color=MUTED, ls="--", lw=1.2, label=f"Noise floor {fl.estimate:.1f} (perfect predictor)")
        for yv, v in zip(yy, r.estimate):
            a.annotate(f"{v:.2f}", (v, yv), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8.5,
                       color=INK_2)
        a.set(yticks=yy, xlabel="Possession-weighted RMSE (net rating points); intervals are marginal,\n"
                     "paired differences are in baseline_metrics.csv",
              title=f"Best baseline is {r.estimate.min() - fl.estimate:.2f} points above the noise floor (n = {n:,})")
        a.set_yticklabels([bl.BASELINES[p] for p in order])
        a.legend(loc="lower right", fontsize=8)
        a.grid(axis="y", visible=False)
        a.set_ylim(-0.7, len(order) - 0.3)
    r = m[(m.weighting == "weighted") & (m.metric == "skill_lm")].set_index("predictor").loc[order[1:]]
    y2 = np.arange(len(r))[::-1]
    ax[1].barh(y2, r.estimate, color=BLUE, height=0.55)
    ax[1].errorbar(r.estimate, y2, xerr=[r.estimate - r.lo, r.hi - r.estimate], fmt="none", ecolor=INK_2,
                   capsize=3, lw=1.2)
    ceil = m[(m.predictor == "noise_floor") & (m.weighting == "weighted") & (m.metric == "r2_ceiling")].iloc[0]
    ax[1].axvline(ceil.estimate, color=ORANGE, ls="--", lw=1.5, label=f"R² ceiling {ceil.estimate:.3f}")
    ax[1].axvline(0, color=MUTED, lw=0.8)
    ax[1].set(yticks=y2, xlabel="Skill vs league mean (1 − MSE / MSE_league mean), weighted",
              title="Explained share of the variance, with the ceiling")
    ax[1].set_yticklabels([bl.BASELINES[p] for p in r.index])
    ax[1].legend(loc="lower right", fontsize=8)
    ax[1].grid(axis="y", visible=False)
    save(fig, FIG / "fig12_baselines_vs_noise_floor.png")


def plot_folds(pf: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    d = pf[(pf.weighting == "weighted") & (pf.metric == "skill_lm")]
    styles = {"team_prior": (BLUE, "o", "-"), "eb_lineup_team": (ORANGE, "s", "-"),
              "player_composite": ("#1baf7a", "^", "-")}
    seasons = sorted(d.val_season.unique())
    x = np.arange(len(seasons))
    for p, (c, mk, ls) in styles.items():
        s = d[d.predictor == p].set_index("val_season").loc[seasons, "value"]
        ax.plot(x, s, color=c, marker=mk, ls=ls, ms=6, label=bl.BASELINES[p])
    ceil = pf[(pf.predictor == "noise_floor") & (pf.weighting == "weighted") & (pf.metric == "r2_ceiling")
              ].set_index("val_season").loc[seasons, "value"]
    ax.plot(x, ceil, color=MUTED, ls="--", lw=1.4, marker="_", ms=14, label="R² ceiling (noise floor)")
    ax.axhline(0, color=MUTED, lw=0.8)
    n = pf[(pf.predictor == "league_mean") & (pf.metric == "rmse") & (pf.weighting == "weighted")].set_index("val_season").n
    ax.set_xticks(x, [f"{s}{'*' if s in IRREGULAR_SEASONS else ''}\n(n = {n[s]})" for s in seasons])
    ax.set(ylabel="Skill vs league mean (weighted)", xlabel="Validation season (* irregular season)",
           title="Baselines move together season by season; the 2019-20 bubble shows no skill")
    ax.legend(loc="upper left", fontsize=8, ncols=2)
    save(fig, FIG / "fig13_baselines_by_fold.png")


def plot_feature_target(q: pd.DataFrame) -> None:
    q = q.sort_values("corr_y_weighted")
    fig, ax = plt.subplots(figsize=(8.5, 5.6))
    yy = np.arange(len(q))
    ax.hlines(yy, q.corr_y_season_min, q.corr_y_season_max, color=BLUE, alpha=0.35, lw=4, label="Range across the six seasons")
    ax.plot(q.corr_y_weighted, yy, "o", color=BLUE, ms=6, label="Pooled (2018-19 to 2023-24)")
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.set_yticks(yy, q.index)
    ax.set(xlabel="Possession-weighted correlation with the post-break net rating",
           title="Feature–target correlations are small, as the noise floor predicts")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="y", visible=False)
    save(fig, FIG / "fig14_feature_target_correlation.png")


def plot_feature_corr(corr: pd.DataFrame) -> None:
    cmap = LinearSegmentedColormap.from_list("div", [ORANGE, "#f1f0ec", BLUE])
    fig, ax = plt.subplots(figsize=(9.2, 7.8))
    im = ax.imshow(corr.to_numpy(), cmap=cmap, vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(corr)), corr.index, fontsize=8)
    for i in range(len(corr)):
        for j in range(len(corr)):
            v = corr.iat[i, j]
            if i != j and abs(v) >= 0.5:
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6.5, color="white" if abs(v) > 0.75 else "#0b0b0b")
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04)
    cb.set_label("Pearson r (labelled where |r| ≥ 0.5)", color=INK_2)
    ax.set_title("Feature correlations: the collinear groups Phase 6 must handle")
    save(fig, FIG / "fig15_feature_correlation.png")


# ---------------------------------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=1000, help="bootstrap replicates")
    args = ap.parse_args()
    apply_style()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    FIG.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        tables = raw.load_pre_break_tables(c, DEV_SEASONS)
        targets = raw.load_targets(c, DEV_SEASONS)
    F["rows_read"] = {"pre_break_lineup_windows": len(tables.lineups), "members": len(tables.members),
                      "player_usage_rows": len(tables.usage), "targets": len(targets)}
    registry.dictionary().to_csv(OUT / "feature_dictionary.csv", index=False)

    builder = FeatureBuilder().fit(tables, DEV_SEASONS)
    full = targets.join(builder.transform(tables, targets).drop(columns=["season_id", "team_id"]), on="lineup_id")
    F["full_dev_fit_parameters"] = builder.params()
    sample(targets, full)
    feature_quality(full, tables)
    baselines(tables, targets, args.boot)
    (OUT / "findings.json").write_text(json.dumps(F, indent=1, default=float) + "\n")
    print(f"\nwrote {OUT / 'findings.json'} and {len(list(FIG.glob('*.png')))} figures in {FIG}")


if __name__ == "__main__":
    main()
