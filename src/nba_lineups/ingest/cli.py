"""Command-line entry point.

    python -m nba_lineups.ingest                         # Phase 1 seasons (2022-23, 2023-24)
    python -m nba_lineups.ingest --seasons 2021-22       # specific seasons
    python -m nba_lineups.ingest --force                 # ignore the cache and refetch everything

Must run from a non-cloud IP: stats.nba.com blocks many datacenter ranges.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ..config import ALL_SEASONS, DEFAULT_DATA_DIR, PHASE1_SEASONS, IngestSettings
from .client import NbaApiTransport
from .pipeline import Ingestor


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m nba_lineups.ingest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seasons", nargs="+", default=list(PHASE1_SEASONS), choices=ALL_SEASONS, metavar="SEASON",
                   help=f"seasons to ingest (default: {' '.join(PHASE1_SEASONS)})")
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--force", action="store_true", help="refetch even if a valid cached file exists")
    p.add_argument("--min-interval", type=float, default=IngestSettings.min_interval_s,
                   help="minimum seconds between requests")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    settings = IngestSettings(min_interval_s=args.min_interval)
    ingestor = Ingestor(NbaApiTransport(settings.timeout_s), args.data_dir, settings)
    summary = ingestor.ingest_seasons(args.seasons, force=args.force)

    print(f"\nrun {summary.run_id}: planned={summary.planned} cached={summary.cached} fetched={summary.fetched} "
          f"refetched_corrupt={summary.refetched_corrupt} failed={summary.failed} invalid={summary.invalid}")
    for problem in summary.problems:
        print("PROBLEM:", problem)
    if not summary.ok:
        print("Some requests did not succeed. Rerun the same command to retry only those.")
    return 0 if summary.ok else 1


if __name__ == "__main__":
    sys.exit(main())
