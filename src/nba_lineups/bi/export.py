"""Export the Power BI dataset: the bi.* star-schema views plus the frozen model's predictions.

Writes to data/powerbi/ (git-ignored: NBA-derived data is never committed):
    csv/<table>.csv         one UTF-8 CSV per table (the Power BI Project reads these)
    LineupLab_dataset.xlsx  every table as a real Excel Table (for Power BI Service in a browser)
    manifest.json           row counts, SHA-256 of each file, model artifact hash, source ETL run

Predictions come from the API's FrozenPredictor: it refuses to run unless the model artifact matches the
committed freeze, and it scores from PRE-break tables only. Nothing here fits, tunes or writes a model.
The observed post-break rating is attached afterwards, by a separate query, as the OUTCOME column.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from ..api.services.predictions import Z95, FrozenPredictor
from ..config import ALL_SEASONS, HELDOUT_SEASONS, PROJECT_ROOT
from ..modeling import raw
from . import model as bim

VIEWS_SQL = PROJECT_ROOT / "sql" / "powerbi" / "bi_views.sql"
DEFAULT_OUT = PROJECT_ROOT / "data" / "powerbi"
WORKBOOK = "LineupLab_dataset.xlsx"


def apply_views(conn: psycopg.Connection) -> None:
    """(Re)create the bi.* views. Touches schema `bi` only."""
    conn.execute(VIEWS_SQL.read_text())
    conn.commit()


def _typed(df: pd.DataFrame, t: bim.Table) -> pd.DataFrame:
    """Columns in model order, cast to the model's types (fails loudly if a view and the model disagree)."""
    names = [c.name for c in t.columns]
    missing = set(names) - set(df.columns)
    if missing:
        raise ValueError(f"{t.name}: columns {sorted(missing)} missing from the source")
    out = df[names].copy()
    for c in t.columns:
        s = out[c.name]
        if c.dtype == "int64":
            out[c.name] = s.astype("Int64") if c.nullable else s.astype("int64")
        elif c.dtype == "double":
            out[c.name] = pd.to_numeric(s, errors="raise").astype("float64")
        elif c.dtype == "dateTime":
            out[c.name] = pd.to_datetime(s).dt.date
        else:
            out[c.name] = s.astype("string")
        if not c.nullable and out[c.name].isna().any():
            raise ValueError(f"{t.name}.{c.name} has unexpected blanks")
    return out


def read_views(conn: psycopg.Connection) -> dict[str, pd.DataFrame]:
    """The bi.* views, limited to the eight evaluated seasons (ALL_SEASONS). The season in progress lives in
    the same warehouse for the dashboard, but the Power BI report is the evaluated-seasons snapshot."""
    out = {}
    for t in bim.TABLES:
        if t.source != "sql":
            continue
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM bi.{t.name}")  # names come from the fixed model definition
            cols = [d.name for d in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
        if "season_id" in df.columns:
            df = df[df.season_id.isin(ALL_SEASONS)].reset_index(drop=True)
        out[t.name] = _typed(df, t)
    if "bridge_lineup_player" in out and "dim_lineup" in out:
        b = out["bridge_lineup_player"]
        out["bridge_lineup_player"] = b[b.lineup_id.isin(out["dim_lineup"].lineup_id)].reset_index(drop=True)
    return out


def predictions(conn: psycopg.Connection, predictor: FrozenPredictor) -> pd.DataFrame:
    """Frozen-model predictions for every lineup that appears after the break, all seasons."""
    frames = []
    for season in ALL_SEASONS:
        f = predictor.season(conn, season).frame          # pre-break features → prediction + baselines
        frames.append(f[["season_id", "team_id", "predicted", "team_prior", "league_mean", "eb_lineup_team",
                         "lu_reliability", "lu_no_history"]].reset_index())
    pred = pd.concat(frames, ignore_index=True)

    # The OUTCOME, read separately and only joined after scoring.
    with conn.cursor() as cur:
        cur.execute("""SELECT lineup_id, poss AS post_poss, coalesce(opp_poss, 0) AS post_opp_poss,
                              net_rating::float8 AS observed_post_net
                       FROM v_lineup_window_ratings WHERE window_type = 'post_asb' AND poss > 0""")
        post = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    df = post.merge(pred, on="lineup_id", how="inner", validate="one_to_one")
    if len(df) != len(post):
        raise RuntimeError(f"{len(post) - len(df)} post-break lineups have no prediction")

    k = predictor.k
    both = (df.post_poss > 0) & (df.post_opp_poss > 0)
    df["noise_var"] = np.where(both, k * (1 / df.post_poss.clip(lower=1) + 1 / df.post_opp_poss.clip(lower=1)), np.nan)
    df["in_evaluation_sample"] = ((df.post_poss >= raw.MIN_TARGET_POSS) & (df.post_opp_poss >= raw.MIN_TARGET_POSS)).astype(int)
    df["is_training_season"] = df.season_id.isin(predictor.trained_seasons).astype(int)
    df["evaluation_set"] = np.where(df.season_id.isin(HELDOUT_SEASONS), "Held-out test", "In-sample (training season)")
    df = df.rename(columns={"predicted": "predicted_net", "team_prior": "team_prior_net", "league_mean": "league_mean_net",
                            "eb_lineup_team": "eb_lineup_net", "lu_reliability": "pre_reliability",
                            "lu_no_history": "pre_no_history"})
    df["model_minus_team_prior"] = df.predicted_net - df.team_prior_net
    ev = df.in_evaluation_sample == 1
    df["predicted_decile"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    for _, idx in df[ev].groupby("season_id").groups.items():
        df.loc[idx, "predicted_decile"] = pd.qcut(df.loc[idx, "predicted_net"].rank(method="first"), 10, labels=False) + 1
    return _typed(df.sort_values(["season_id", "lineup_id"]).reset_index(drop=True), bim.table("fact_prediction"))


def parameters(predictor: FrozenPredictor) -> pd.DataFrame:
    vc = predictor.model.builder.lineup_vc_
    row = {"k_noise": float(predictor.k), "lineup_tau2": float(vc.tau2), "lineup_mu": float(vc.mu),
           "model_sd": float(predictor.model_sd), "z95": Z95, "min_target_poss": raw.MIN_TARGET_POSS,
           "artifact_sha256": predictor.artifact_sha256, "frozen_at_utc": predictor.spec.get("frozen_at_utc", ""),
           "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return _typed(pd.DataFrame([row]), bim.table("model_parameters"))


def build_dataset(conn: psycopg.Connection, predictor: FrozenPredictor) -> dict[str, pd.DataFrame]:
    data = read_views(conn)
    data["fact_prediction"] = predictions(conn, predictor)
    data["model_parameters"] = parameters(predictor)
    return {t.name: data[t.name] for t in bim.data_tables()}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_dataset(data: dict[str, pd.DataFrame], out: Path = DEFAULT_OUT, excel: bool = True) -> dict:
    csv_dir = out / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, df in data.items():
        p = csv_dir / f"{name}.csv"
        df.to_csv(p, index=False, lineterminator="\n", float_format="%.10g")
        files[f"csv/{name}.csv"] = {"rows": len(df), "sha256": _sha(p)}
    # The measures host table: one placeholder row, so the browser route has a table to attach measures to.
    p = csv_dir / "_Measures.csv"
    pd.DataFrame({"_": ["measures"]}).to_csv(p, index=False, lineterminator="\n")
    files["csv/_Measures.csv"] = {"rows": 1, "sha256": _sha(p)}

    if excel:
        xp = out / WORKBOOK
        _write_workbook({**data, "_Measures": pd.DataFrame({"_": ["measures"]})}, xp)
        files[WORKBOOK] = {"rows": int(sum(len(d) for d in data.values())), "sha256": _sha(xp)}

    params = data["model_parameters"].iloc[0]
    manifest = {"exported_at_utc": params.exported_at_utc, "model_artifact_sha256": params.artifact_sha256,
                "tables": {n: len(d) for n, d in data.items()}, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _write_workbook(data: dict[str, pd.DataFrame], path: Path) -> None:
    """One worksheet per table, each formatted as an Excel Table named like the model table (Power BI imports
    Excel *tables*, and keeps their names)."""
    with pd.ExcelWriter(path, engine="xlsxwriter", date_format="yyyy-mm-dd") as xw:
        for name, df in data.items():
            df = df.astype(object).where(df.notna(), None)
            sheet = name[:31]
            df.to_excel(xw, sheet_name=sheet, index=False, startrow=1, header=False)
            ws = xw.sheets[sheet]
            n_rows, n_cols = df.shape
            ws.add_table(0, 0, max(n_rows, 1), n_cols - 1,
                         {"name": name,
                          "columns": [{"header": c} for c in df.columns], "style": "Table Style Light 9"})
