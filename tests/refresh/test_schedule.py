"""When the scheduled refresh runs: 07:00 Toronto, catch-up after sleep/shutdown, retry cap, single instance,
and the launchd agent definition. Offline."""
from __future__ import annotations

import plistlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nba_lineups.config import PROJECT_ROOT
from nba_lineups.refresh import schedule
from nba_lineups.refresh.lock import AlreadyRunning, RefreshLock

TOR = ZoneInfo("America/Toronto")


def at(day: int, h: int, m: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, h, m, tzinfo=TOR)


def succeeded(when: datetime) -> schedule.LocalState:
    return schedule.record_attempt(schedule.LocalState(), when, "success", "ok", success=True)


def test_latest_slot_is_the_most_recent_7am_toronto():
    assert schedule.latest_slot(at(20, 6, 59)) == at(19, 7)
    assert schedule.latest_slot(at(20, 7, 0)) == at(20, 7)
    assert schedule.latest_slot(at(20, 23)) == at(20, 7)
    # the same instant expressed in another zone gives the same slot
    assert schedule.latest_slot(at(20, 7, 30).astimezone(ZoneInfo("Asia/Tokyo"))) == at(20, 7)


def test_runs_once_per_day_after_7am():
    s = succeeded(at(20, 7, 2))
    assert not schedule.is_due(s, at(20, 8))[0]               # hourly checks the same day are no-ops
    assert not schedule.is_due(s, at(21, 6, 59))[0]           # still before the next slot
    assert schedule.is_due(s, at(21, 7))[0]                   # next morning


def test_missed_slot_while_asleep_or_off_runs_at_next_wake_or_login():
    s = succeeded(at(19, 7, 1))
    assert schedule.is_due(s, at(20, 11, 37))[0]              # Mac woke at 11:37: catch up now
    assert schedule.is_due(s, at(23, 9))[0]                   # off for days: one catch-up run, not several
    s = schedule.record_attempt(s, at(23, 9), "success", "ok", success=True)
    assert not schedule.is_due(s, at(23, 10))[0]


def test_never_refreshed_is_due():
    assert schedule.is_due(schedule.LocalState(), at(20, 3))[0]


def test_failures_retry_hourly_up_to_a_daily_cap_then_wait_for_tomorrow():
    s = succeeded(at(19, 7))
    t = at(20, 7)
    for i in range(schedule.MAX_ATTEMPTS_PER_DAY):
        assert schedule.is_due(s, t)[0], i
        s = schedule.record_attempt(s, t, "failed", "database unavailable", success=False)
        t += timedelta(hours=1)
    due, why = schedule.is_due(s, t)
    assert not due and "failed attempts" in why
    assert schedule.is_due(s, at(21, 7))[0]                   # the cap resets at the next slot


def test_state_file_roundtrip_and_corrupt_file(tmp_path):
    p = tmp_path / "state.json"
    succeeded(at(20, 7)).save(p)
    assert schedule.LocalState.load(p).last_success_at.startswith("2026-11-20T07:00")
    p.write_text("{not json")
    assert schedule.LocalState.load(p) == schedule.LocalState()


def test_lock_prevents_overlapping_refreshes(tmp_path):
    lock = tmp_path / "refresh.lock"
    with RefreshLock(lock):
        with pytest.raises(AlreadyRunning):
            with RefreshLock(lock):
                pass
    with RefreshLock(lock):                                   # released after the first run ends
        pass


def test_launchd_agent_definition():
    raw = (PROJECT_ROOT / "scripts" / "refresh" / "com.lineuplab.daily-refresh.plist.template").read_bytes()
    plist = plistlib.loads(raw.replace(b"__PROJECT__", b"/p"))
    assert plist["ProgramArguments"] == ["/p/.venv/bin/python", "-m", "nba_lineups.refresh", "--if-due"]
    assert plist["StartCalendarInterval"] == {"Hour": 7, "Minute": 0}
    assert plist["StartInterval"] == 3600 and plist["RunAtLoad"] is True   # catch-up after sleep, shutdown, failure
    assert plist["WorkingDirectory"] == "/p"
