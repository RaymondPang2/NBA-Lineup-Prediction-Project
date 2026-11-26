"""Container start-up for the public demo: wait for PostgreSQL, then build any SYNTHETIC demo season that is not loaded
yet. Safe on every start: a fully seeded database is left untouched; a partly seeded one is completed.

    python -m nba_lineups.demo.seed            # uses DATABASE_URL
"""
from __future__ import annotations

import logging
import os
import sys
import time

import psycopg

from .build import build_demo, loaded_seasons
from .league import DEMO_SEASONS

log = logging.getLogger("nba_lineups.demo.seed")


def is_seeded(url: str) -> bool:
    """Seeded = EVERY demo season is loaded (not just one: a build interrupted mid-way must resume)."""
    with psycopg.connect(url, connect_timeout=5) as c:
        return set(DEMO_SEASONS) <= loaded_seasons(c)


def main(wait_s: float = 120) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set")
        return 1
    deadline = time.monotonic() + wait_s
    while True:
        try:
            seeded = is_seeded(url)
            break
        except psycopg.OperationalError as exc:
            if time.monotonic() > deadline:
                log.error("database unreachable: %s", exc)
                return 1
            log.info("waiting for the database ...")
            time.sleep(3)
    if seeded:
        log.info("demo database already seeded; nothing to do")
        return 0
    log.info("building the missing synthetic demo seasons (fictional data)")
    counts = build_demo(url)
    log.info("demo database ready: %s", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
