"""Append-only ingestion log (JSON Lines).

One JSON object per line, one line per fetch attempt outcome. Appending never
rewrites history, so the log is a trustworthy audit trail. Phase 2 loads it
into the `ingestion_runs` table.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUCCESS, FAILED, INVALID = "success", "failed", "invalid"


@dataclass
class IngestionRecord:
    run_id: str
    request_key: str
    endpoint: str
    season: str
    window: str | None
    measure: str | None
    team_id: int | None
    params: dict[str, Any]
    status: str
    attempts: int
    duration_s: float
    row_count: int | None = None
    raw_path: str | None = None
    sha256: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: IngestionRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    def records(self) -> list[dict[str, Any]]:
        """All parseable records. A crash mid-append can only damage the last line, so bad lines are skipped."""
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
