"""When is a scheduled refresh due? Pure logic over a small local state file, no database and no network.

launchd starts the job at 07:00 and also every hour, at login and on wake (docs/refresh.md). Each start
asks `is_due`; only the first start after today's 07:00 America/Toronto that finds no successful refresh
since then does any work. That one rule covers every case:

* the Mac was awake at 07:00                       -> runs at 07:00;
* asleep or shut down at 07:00                     -> runs at the first start after wake / login;
* the refresh failed (NBA API down, database down) -> retried at the next hourly start, at most
  MAX_ATTEMPTS_PER_DAY times, then it waits for tomorrow (no hammering a failing source);
* already refreshed today                          -> exits at once, without touching the network.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..ingest.storage import atomic_write_json

LOCAL_TZ = ZoneInfo("America/Toronto")
DAILY_AT = time(7, 0)
MAX_ATTEMPTS_PER_DAY = 8


@dataclass
class LocalState:
    last_success_at: str | None = None       # ISO, timezone-aware
    last_attempt_at: str | None = None
    last_status: str | None = None
    last_message: str | None = None
    attempts_since_slot: int = 0             # attempts since the most recent 07:00 slot
    slot: str | None = None                  # ISO of the slot attempts_since_slot refers to

    @classmethod
    def load(cls, path: Path) -> LocalState:
        try:
            raw = json.loads(path.read_text())
            return cls(**{k: raw.get(k) for k in cls.__dataclass_fields__ if k in raw})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path) -> None:
        atomic_write_json(path, asdict(self))


def latest_slot(now: datetime) -> datetime:
    """The most recent 07:00 America/Toronto at or before `now`."""
    local = now.astimezone(LOCAL_TZ)
    slot = datetime.combine(local.date(), DAILY_AT, LOCAL_TZ)
    return slot if local >= slot else datetime.combine(local.date() - timedelta(days=1), DAILY_AT, LOCAL_TZ)


def is_due(state: LocalState, now: datetime) -> tuple[bool, str]:
    slot = latest_slot(now)
    if state.last_success_at and datetime.fromisoformat(state.last_success_at) >= slot:
        return False, f"already refreshed since {slot.isoformat()}"
    attempts = state.attempts_since_slot if state.slot == slot.isoformat() else 0
    if attempts >= MAX_ATTEMPTS_PER_DAY:
        return False, f"{attempts} failed attempts since {slot.isoformat()}; next try after the next 07:00"
    return True, f"no successful refresh since {slot.isoformat()}"


def record_attempt(state: LocalState, now: datetime, status: str, message: str, success: bool) -> LocalState:
    slot = latest_slot(now).isoformat()
    attempts = (state.attempts_since_slot if state.slot == slot else 0) + 1
    state.slot, state.attempts_since_slot = slot, attempts
    state.last_attempt_at, state.last_status, state.last_message = now.isoformat(timespec="seconds"), status, message
    if success:
        state.last_success_at = now.isoformat(timespec="seconds")
    return state
