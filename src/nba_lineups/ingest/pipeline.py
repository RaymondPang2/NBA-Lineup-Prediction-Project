"""Cache-aware, resumable ingestion.

For each RequestSpec:
    valid cached file?  -> skip (this is what makes a rerun resume where it stopped)
    otherwise           -> rate-limited fetch with retries
                        -> validate
                        -> valid:   atomic write to data/raw/,        log 'success'
                           invalid: write to data/quarantine/,        log 'invalid'
                           network failure after retries:              log 'failed'
One bad request never aborts the run; failures are summarized at the end.
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import IngestSettings
from .client import FetchFailed, RateLimiter, Transport, fetch_with_retries
from .manifest import FAILED, INVALID, SUCCESS, IngestionRecord, Manifest
from .specs import RequestSpec, gamelog_spec, season_specs
from .storage import atomic_write_json, read_json, result_set
from .validate import validate_payload
from .windows import DateWindow, build_windows

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: str
    planned: int = 0
    cached: int = 0
    fetched: int = 0
    refetched_corrupt: int = 0
    failed: int = 0
    invalid: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.invalid == 0 and not self.problems


class Ingestor:
    def __init__(self, transport: Transport, data_dir: Path, settings: IngestSettings = IngestSettings(),
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 rng: Callable[[], float] = random.random, run_id: str | None = None) -> None:
        self.transport, self.settings = transport, settings
        self.data_dir = data_dir
        self.raw_dir, self.quarantine_dir = data_dir / "raw", data_dir / "quarantine"
        self.manifest = Manifest(data_dir / "ingestion_log.jsonl")
        self._sleep, self._clock, self._rng = sleep, clock, rng
        self.limiter = RateLimiter(settings.min_interval_s, settings.jitter_s, clock, sleep, rng)
        self.run_id = run_id or uuid.uuid4().hex[:12]

    # ---- single request -------------------------------------------------
    def ingest_one(self, spec: RequestSpec, summary: RunSummary, force: bool = False) -> dict[str, Any] | None:
        """Return a valid payload for spec (cached or fresh), or None if it could not be obtained."""
        summary.planned += 1
        path = spec.cache_path(self.raw_dir)

        if path.exists() and not force:
            cached = read_json(path)
            if cached is not None and validate_payload(spec, cached).ok:
                summary.cached += 1
                return cached
            log.warning("%s: cached file is corrupt or no longer valid; refetching", spec.key)
            summary.refetched_corrupt += 1

        start = self._clock()
        try:
            payload, attempts = fetch_with_retries(self.transport, spec, self.settings, self.limiter, self._sleep, self._rng)
        except FetchFailed as exc:
            summary.failed += 1
            self._record(spec, FAILED, exc.attempts, start, errors=[repr(exc.last_error)])
            log.error("%s", exc)
            return None

        report = validate_payload(spec, payload)
        if not report.ok:
            summary.invalid += 1
            qpath = spec.cache_path(self.quarantine_dir)
            sha = atomic_write_json(qpath, payload)
            self._record(spec, INVALID, attempts, start, report.row_count, qpath, sha, report.errors, report.warnings)
            log.error("%s: invalid payload quarantined: %s", spec.key, "; ".join(report.errors))
            return None

        sha = atomic_write_json(path, payload)
        summary.fetched += 1
        self._record(spec, SUCCESS, attempts, start, report.row_count, path, sha, warnings=report.warnings)
        return payload

    def _record(self, spec: RequestSpec, status: str, attempts: int, start: float, row_count: int | None = None,
                path: Path | None = None, sha: str | None = None, errors: list[str] | None = None,
                warnings: list[str] | None = None) -> None:
        self.manifest.append(IngestionRecord(
            run_id=self.run_id, request_key=spec.key, endpoint=spec.endpoint, season=spec.season,
            window=spec.window, measure=spec.measure, team_id=spec.team_id, params=spec.kwargs, status=status,
            attempts=attempts, duration_s=round(self._clock() - start, 3), row_count=row_count,
            # store paths relative to data_dir so the log is portable and contains no home-directory paths
            raw_path=str(path.relative_to(self.data_dir)) if path else None,
            sha256=sha, errors=errors or [], warnings=warnings or [],
        ))

    # ---- whole seasons ----------------------------------------------------
    def ingest_season(self, season: str, summary: RunSummary, force: bool = False) -> None:
        gamelog = self.ingest_one(gamelog_spec(season), summary, force)
        if gamelog is None:
            summary.problems.append(f"{season}: game log unavailable; season skipped")
            return
        dates, team_ids = gamelog_dates_and_teams(gamelog)
        windows = build_windows(season, dates)
        self._write_windows(season, windows)
        log.info("%s windows: %s", season, {w.name: (w.date_from.isoformat(), w.date_to.isoformat()) for w in windows.values()})

        specs = season_specs(season, windows, team_ids)
        for i, spec in enumerate(specs, 1):
            self.ingest_one(spec, summary, force)
            if i % 25 == 0 or i == len(specs):
                log.info("%s: %d/%d requests processed (cached=%d fetched=%d failed=%d invalid=%d)",
                         season, i, len(specs), summary.cached, summary.fetched, summary.failed, summary.invalid)

    def ingest_seasons(self, seasons: Iterable[str], force: bool = False) -> RunSummary:
        summary = RunSummary(self.run_id)
        for season in seasons:
            self.ingest_season(season, summary, force)
        return summary

    def _write_windows(self, season: str, windows: dict[str, DateWindow]) -> None:
        atomic_write_json(self.raw_dir / season / "windows.json", {k: w.to_dict() for k, w in windows.items()})


def gamelog_dates_and_teams(payload: dict[str, Any]) -> tuple[list[date], list[int]]:
    headers, rows = result_set(payload)
    df = pd.DataFrame(rows, columns=headers)
    dates = pd.to_datetime(df.GAME_DATE).dt.date.unique().tolist()
    return sorted(dates), sorted(int(t) for t in df.TEAM_ID.unique())
