"""Phase 9: (re)create the bi.* views and export the Power BI dataset.

    .venv/bin/python scripts/phase9/export_powerbi.py              # CSVs + Excel workbook + manifest
    .venv/bin/python scripts/phase9/export_powerbi.py --no-excel   # CSVs only (faster)

Output: data/powerbi/ (git-ignored). Needs PostgreSQL (docker compose up -d) and the committed frozen model.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from nba_lineups.api.services.predictions import FrozenPredictor
from nba_lineups.bi import export
from nba_lineups.config import PROJECT_ROOT
from nba_lineups.db.connection import connect


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=export.DEFAULT_OUT)
    ap.add_argument("--no-excel", action="store_true", help="skip the Excel workbook")
    args = ap.parse_args()

    t0 = time.time()
    predictor = FrozenPredictor(PROJECT_ROOT / "models" / "final", PROJECT_ROOT / "reports", require_git_freeze=True)
    with connect() as conn:
        export.apply_views(conn)
        data = export.build_dataset(conn, predictor)
    if not predictor.verify():
        raise SystemExit("frozen model changed during export")
    manifest = export.write_dataset(data, args.out, excel=not args.no_excel)
    for name, n in manifest["tables"].items():
        print(f"  {name:<22} {n:>9,} rows")
    print(f"wrote {args.out} in {time.time() - t0:.1f}s (model {manifest['model_artifact_sha256'][:12]}…)")


if __name__ == "__main__":
    main()
