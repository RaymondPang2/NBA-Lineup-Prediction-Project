"""Reproducible feature build (development seasons only).

    .venv/bin/python -m nba_lineups.modeling.build [--out data/features]

Writes (under data/, which is git-ignored because it holds NBA-derived data):
    lineup_features_dev.csv.gz   one row per modeling-sample lineup: ids, target, weight, features.
                                 Builder fitted on ALL development seasons (for exploration and the
                                 final Phase 6 fit). Cross-validation refits it inside each fold instead.
    manifest.json                git commit, seasons, row counts, fitted parameters, SHA-256 of the file
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..config import DEFAULT_DATA_DIR, DEV_SEASONS, HELDOUT_SEASONS, PROJECT_ROOT
from ..db.connection import connect
from . import raw
from .features import FeatureBuilder
from .registry import FEATURE_NAMES


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build(out_dir: Path) -> dict:
    with connect() as conn:
        tables = raw.load_pre_break_tables(conn, DEV_SEASONS)
        targets = raw.load_targets(conn, DEV_SEASONS)
    builder = FeatureBuilder().fit(tables, DEV_SEASONS)
    x = builder.transform(tables, targets).drop(columns=["season_id", "team_id"])
    df = targets.join(x, on="lineup_id")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "lineup_features_dev.csv.gz"
    df.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})  # mtime 0: byte-identical rebuilds
    manifest = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(), "seasons": list(DEV_SEASONS), "held_out_not_read": list(HELDOUT_SEASONS),
        "rows": len(df), "rows_by_season": df.season_id.value_counts().sort_index().to_dict(),
        "features": list(FEATURE_NAMES), "fitted_parameters": builder.params(),
        "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, default=float) + "\n")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR / "features")
    m = build(ap.parse_args().out)
    print(f"wrote {m['rows']} rows ({m['rows_by_season']}) to {m['file']}, sha256 {m['sha256'][:12]}")


if __name__ == "__main__":
    main()
