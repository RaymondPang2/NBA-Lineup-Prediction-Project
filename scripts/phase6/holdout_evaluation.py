"""Phase 6 FINAL TEST: evaluate the frozen model on the held-out seasons, exactly as pre-registered in
models/final/frozen_spec.json. Run once, after models/final/ is committed. Nothing here refits or retunes.

    .venv/bin/python scripts/phase6/holdout_evaluation.py

Refuses to run (NotFrozenError) unless the frozen spec and artifact are committed and unchanged.
Writes reports/phase6/holdout/{holdout_metrics.csv, holdout_by_history.csv, holdout_findings.json} and
reports/phase6/figures/fig22-fig23.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from nba_lineups.analysis import reliability as rel
from nba_lineups.analysis.plotting import BLUE, INK_2, MUTED, ORANGE, apply_style, save
from pathlib import Path

from nba_lineups.config import HELDOUT_SEASONS, PROJECT_ROOT
from nba_lineups.db.connection import connect
from nba_lineups.modeling import baselines as bl
from nba_lineups.modeling import evaluation as ev
from nba_lineups.modeling import final, holdout, raw

MODEL_DIR = PROJECT_ROOT / "models" / "final"
OUT = PROJECT_ROOT / "reports" / "phase6" / "holdout"
FIG = PROJECT_ROOT / "reports" / "phase6" / "figures"
N_BOOT, SEED = 2000, 2025          # as written in the frozen evaluation plan
BASE = bl.PRIMARY


def main() -> None:
    global OUT, FIG
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", type=Path, metavar="DIR",
                    help="exercise the code on development season 2023-24 (in-sample, meaningless numbers) and write "
                         "to DIR; does NOT unlock or read the held-out seasons")
    args = ap.parse_args()
    apply_style()
    pd.set_option("display.width", 250)
    seasons = list(HELDOUT_SEASONS)
    if args.dry_run:
        key, seasons, OUT, FIG = None, ["2023-24"], args.dry_run, args.dry_run
        print("DRY RUN on 2023-24 (development season): code check only")
    else:
        key = holdout.unlock(MODEL_DIR)                   # raises unless the frozen model is committed
    spec = json.loads((MODEL_DIR / final.SPEC).read_text())
    model = final.load(MODEL_DIR)
    m = model.model_name
    assert m == spec["model"]["name"] and model.params == spec["model"]["params"]
    if key is not None:
        print(f"unlocked with frozen spec {key.spec_sha256[:12]} (frozen at {spec['frozen_at_utc']}); model = {m}")

    with connect() as c:
        tables = raw.load_pre_break_tables(c, seasons, key=key)
        targets = raw.load_targets(c, seasons, key=key)
    frame = model.feature_frame(tables, targets)
    frame[m] = model.predict_frame(frame)
    frame = frame.join(model.baseline_predictions(frame))
    frame["k"] = model.noise_k
    preds = BASE + [m]
    OUT.mkdir(parents=True, exist_ok=True)

    results, F = [], {"spec_sha256": key.spec_sha256 if key else "dry-run", "artifact_sha256": spec["artifact"]["sha256"],
                      "model": spec["model"], "evaluated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "n_boot": N_BOOT, "seed": SEED, "evaluations": {}}
    for name, d in [(s, frame[frame.season_id == s]) for s in seasons] + [("pooled", frame)]:
        ci = ev.bootstrap_comparison(d, preds, [m], BASE, n_boot=N_BOOT, seed=SEED)
        ci.insert(0, "evaluation", name)
        results.append(ci)
        F["evaluations"][name] = {"n": len(d), "effective_n": rel.kish_effective_n(d.w),
                                  "no_history_share": float(d.lu_no_history.mean()),
                                  "metrics": {f"{r.predictor}|{r.weighting}|{r.metric}": [round(r.estimate, 4), round(r.lo, 4), round(r.hi, 4)]
                                              for r in ci.itertuples()}}
        print(f"\n=== {name}: n = {len(d)}, effective n {rel.kish_effective_n(d.w):.0f}")
        for wt in ("weighted", "unweighted"):
            t = ci[(ci.weighting == wt) & ci.metric.isin(["rmse", "mae", "r2", "rmse_floor", "r2_ceiling", "mae_floor"])]
            t = t.assign(v=[f"{e:.3f} [{lo:.3f}, {hi:.3f}]" for e, lo, hi in zip(t.estimate, t.lo, t.hi)])
            print(f"[{wt}]")
            print(t.pivot_table(index="predictor", columns="metric", values="v", aggfunc="first").to_string())
            dd = ci[(ci.weighting == wt) & ci.metric.str.contains("_minus_") | (ci.weighting == wt) & (ci.metric == "calibration_slope")]
            print("\n".join(f"  {r.metric}: {r.estimate:+.3f} [{r.lo:+.3f}, {r.hi:+.3f}]" for r in dd.itertuples()))
    res = pd.concat(results, ignore_index=True)
    res.round(5).to_csv(OUT / "holdout_metrics.csv", index=False)

    rows = []
    for label, d in (("no pre-break history", frame[frame.lu_no_history == 1]),
                     ("history < 100 poss", frame[(frame.lu_no_history == 0) & (frame.lu_poss < 100)]),
                     ("history >= 100 poss", frame[frame.lu_poss >= 100])):
        ci = ev.bootstrap_comparison(d, preds, [m], ["team_prior", "league_mean"], n_boot=N_BOOT, seed=SEED)
        rows.append(ci.assign(group=label, n=len(d)))
    hist = pd.concat(rows, ignore_index=True)
    hist.round(5).to_csv(OUT / "holdout_by_history.csv", index=False)
    w = hist[(hist.weighting == "weighted") & hist.metric.isin(["rmse", "rmse_floor", "rmse_minus_team_prior"])]
    print("\n=== pooled, by pre-break history (weighted)")
    print(w[w.predictor.isin([m, "team_prior", "league_mean", "noise_floor"])].pivot_table(
        index=["group", "n"], columns=["predictor", "metric"], values="estimate").round(3).to_string())
    F["by_history_weighted"] = {f"{r.group}|{r.predictor}|{r.metric}": [round(r.estimate, 4), round(r.lo, 4), round(r.hi, 4)]
                                for r in w.itertuples()}
    cal = ev.calibration_bins(frame.y, frame[m], frame.w)
    cal.round(4).to_csv(OUT / "holdout_calibration_bins.csv")
    (OUT / "holdout_findings.json").write_text(json.dumps(F, indent=1, default=float) + "\n")
    plot(res, m, cal, frame, seasons)
    print(f"\nwrote {OUT}")


def plot(res: pd.DataFrame, m: str, cal: pd.DataFrame, frame: pd.DataFrame, seasons: list[str]) -> None:
    evals = list(seasons) + ["pooled"]
    refs = ["league_mean", "team_prior", "eb_lineup_team", "player_composite"]
    labels = {"league_mean": "vs league mean", "team_prior": "vs team prior", "eb_lineup_team": "vs EB lineup",
              "player_composite": "vs player composite"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axes[0]
    colors = dict(zip(evals, [BLUE, ORANGE, INK_2]))
    yy = np.arange(len(refs))[::-1]
    for i, e in enumerate(evals):
        d = res[(res.evaluation == e) & (res.weighting == "weighted")].set_index("metric")
        for yv, b in zip(yy, refs):
            r = d.loc[f"rmse_minus_{b}"]
            ax.errorbar([r.estimate], [yv + (1 - i) * 0.22], xerr=[[r.estimate - r.lo], [r.hi - r.estimate]], fmt="o",
                        color=colors[e], ms=6, capsize=3, lw=1.6, label=e if yv == yy[0] else None)
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_yticks(yy, [labels[b] for b in refs])
    ax.set(xlabel="Weighted RMSE: frozen model minus baseline (left of 0 = model better), 95% CI",
           title="Final test on held-out seasons (frozen model, no retuning)")
    ax.legend(title="Held-out evaluation", fontsize=8, title_fontsize=8, loc="upper center",
              bbox_to_anchor=(0.5, -0.17), ncols=3)
    ax.grid(axis="y", visible=False)
    ax = axes[1]
    ax.errorbar(cal.mean_pred, cal.mean_y, yerr=1.96 * cal.se_y, fmt="o-", color=BLUE, ms=5, capsize=2, lw=1.4,
                label="Frozen model, prediction deciles (pooled)")
    lo, hi = cal.mean_pred.min() - 1, cal.mean_pred.max() + 1
    ax.plot([lo, hi], [lo, hi], color=INK_2, ls="--", lw=1, label="Perfect calibration")
    ax.set(xlabel="Mean prediction (weighted)", ylabel="Mean actual post-break net rating (weighted)",
           title=f"Held-out calibration (slope {ev.calibration_slope(frame.y, frame[m], frame.w):.2f})")
    ax.legend(fontsize=8, loc="upper left")
    save(fig, FIG / "fig22_holdout_final_test.png",
         source="Held-out seasons 2024-25 and 2025-26, read once after the model was frozen and committed. "
                "Team-season cluster bootstrap (2,000). NBA.com/stats via nba_api.")


if __name__ == "__main__":
    main()
