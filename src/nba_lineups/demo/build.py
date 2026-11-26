"""Build the public demo database from the SYNTHETIC league through the real pipeline.

    python -m nba_lineups.demo.build --database-url postgresql://...      # loads an EMPTY database

Steps: synthetic transport -> the real Ingestor (validation, cache, manifest) into a temporary raw directory -> the
real ETL (transform, one-transaction load, error-level data-quality gate) for each demo season. A failed check
aborts the build. The resulting database is what `deploy/demo_seed.sql.gz` is dumped from (scripts/demo/).
"""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

import psycopg

from ..config import IngestSettings
from ..db.connection import apply_schema
from ..etl.extract import read_season
from ..etl.load import load_season
from ..etl.transform import transform_season
from ..ingest.pipeline import Ingestor
from .league import DEMO_SEASONS, SyntheticTransport, build

log = logging.getLogger("nba_lineups.demo")
FAST = IngestSettings(min_interval_s=0, jitter_s=0, max_attempts=1)
SEED_LOCK = 7_202_628


def loaded_seasons(conn: psycopg.Connection) -> set[str]:
    if conn.execute("SELECT to_regclass('seasons') IS NULL").fetchone()[0]:
        return set()
    return {r[0] for r in conn.execute("SELECT season_id FROM seasons")}


def build_demo(database_url: str, data_dir: Path | None = None) -> dict[str, dict[str, int]]:
    """Load every demo season that is missing (each season in one transaction). Resumable: a start interrupted
    mid-build loads the remaining seasons next time. Refuses a database that holds any non-demo season."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        present = loaded_seasons(conn)
    foreign = present - set(DEMO_SEASONS)
    if foreign:
        raise RuntimeError(f"database holds non-demo seasons {sorted(foreign)}; refusing to write demo data into it")
    todo = {s: kw for s, kw in DEMO_SEASONS.items() if s not in present}
    if not todo:
        return {}
    league = build(todo)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(data_dir or tmp)
        ing = Ingestor(SyntheticTransport(league), d, FAST, sleep=lambda s: None)
        summary = ing.ingest_seasons(list(league))
        if not summary.ok:
            raise RuntimeError(f"synthetic ingestion failed: {summary.problems or summary}")
        counts = {}
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("SELECT pg_advisory_lock(%s)", (SEED_LOCK,))   # one seeder at a time
            apply_schema(conn)
            already = loaded_seasons(conn)                           # another start may have finished meanwhile
            for s in [x for x in league if x not in already]:
                c, dq = load_season(conn, transform_season(read_season(d / "raw", s)))
                warn = [f"{r.name}={r.violations}" for r in dq if not r.passed]
                log.info("%s: %s | DQ warnings: %s", s, c, ", ".join(warn) or "none")
                counts[s] = c
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m nba_lineups.demo.build", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", required=True)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    print(build_demo(args.database_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
