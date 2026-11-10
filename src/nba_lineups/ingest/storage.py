"""Atomic JSON persistence.

Writing to a temporary file and then calling os.replace() is atomic on the
same filesystem. A reader therefore sees either the old file or the complete
new one, never a half-written file. This is what makes the cache safe to use
as a resume checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: Any) -> str:
    """Write payload as JSON atomically and return the SHA-256 of the bytes written."""
    data = json.dumps(payload, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())  # make sure the bytes are on disk before the rename
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any | None:
    """Return parsed JSON, or None if the file is missing or unreadable or corrupt."""
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None


def result_set(payload: dict[str, Any], index: int = 0) -> tuple[list[str], list[list[Any]]]:
    """Return (headers, rows) from a stats.nba.com payload. Raises KeyError/IndexError/TypeError if malformed."""
    rs = payload["resultSets"][index]
    return list(rs["headers"]), list(rs["rowSet"])
