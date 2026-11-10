"""End-to-end pipeline behaviour with a fake transport: caching, resume, failures, quarantine."""
import json

import pytest

from nba_lineups.ingest.manifest import FAILED, INVALID, SUCCESS, Manifest
from nba_lineups.ingest.pipeline import Ingestor

from ..conftest import SEASON, FakeTransport

PER_SEASON = 1 + 2 + 2 + 180  # game log + team + player + lineup requests
FIRST_LINEUP = f"{SEASON}/leaguedashlineups/pre_asb/advanced/team_1610612737"


def make(transport, tmp_path, clock, settings):
    return Ingestor(transport, tmp_path, settings, sleep=clock.sleep, clock=clock, rng=lambda: 0.0, run_id="test")


def test_full_run_fetches_validates_and_logs(tmp_path, clock, fast_settings):
    t = FakeTransport()
    s = make(t, tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert s.ok and s.fetched == PER_SEASON and s.planned == PER_SEASON
    assert len(t.calls) == PER_SEASON
    records = Manifest(tmp_path / "ingestion_log.jsonl").records()
    assert len(records) == PER_SEASON and {r["status"] for r in records} == {SUCCESS}
    assert all(not r["raw_path"].startswith("/") for r in records)  # relative paths only
    windows = json.loads((tmp_path / "raw" / SEASON / "windows.json").read_text())
    assert windows["pre_asb"]["date_to"] == "2024-02-15" and windows["post_asb"]["date_from"] == "2024-02-22"


def test_second_run_is_fully_cached(tmp_path, clock, fast_settings):
    make(FakeTransport(), tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    t2 = FakeTransport()
    s = make(t2, tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert t2.calls == [] and s.cached == PER_SEASON and s.ok  # idempotent: no network on rerun


def test_interrupted_run_resumes_where_it_stopped(tmp_path, clock, fast_settings):
    with pytest.raises(KeyboardInterrupt):
        make(FakeTransport(interrupt_after=50), tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    t2 = FakeTransport()
    s = make(t2, tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert s.cached == 50 and s.fetched == PER_SEASON - 50 and len(t2.calls) == PER_SEASON - 50


def test_corrupt_cache_file_is_refetched(tmp_path, clock, fast_settings):
    make(FakeTransport(), tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    victim = tmp_path / "raw" / f"{FIRST_LINEUP}.json"
    victim.write_text('{"resultSets": [')
    t2 = FakeTransport()
    s = make(t2, tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert t2.calls == [FIRST_LINEUP] and s.refetched_corrupt == 1 and s.ok


def test_persistent_failure_is_logged_and_run_continues(tmp_path, clock, fast_settings):
    t = FakeTransport(fail_times={FIRST_LINEUP: 99})
    s = make(t, tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert s.failed == 1 and s.fetched == PER_SEASON - 1 and not s.ok
    failed = [r for r in Manifest(tmp_path / "ingestion_log.jsonl").records() if r["status"] == FAILED]
    assert [r["request_key"] for r in failed] == [FIRST_LINEUP] and failed[0]["attempts"] == 3
    # the network recovers -> a rerun fetches only the missing request
    t2 = FakeTransport()
    s2 = make(t2, tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert t2.calls == [FIRST_LINEUP] and s2.ok


def test_invalid_payload_is_quarantined_not_cached(tmp_path, clock, fast_settings):
    s = make(FakeTransport(invalid_keys={FIRST_LINEUP}), tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert s.invalid == 1 and not s.ok
    assert not (tmp_path / "raw" / f"{FIRST_LINEUP}.json").exists()
    assert (tmp_path / "quarantine" / f"{FIRST_LINEUP}.json").exists()
    rec = next(r for r in Manifest(tmp_path / "ingestion_log.jsonl").records() if r["status"] == INVALID)
    assert any("truncated" in e for e in rec["errors"])


def test_missing_gamelog_skips_season(tmp_path, clock, fast_settings):
    t = FakeTransport(fail_times={f"{SEASON}/leaguegamelog/league": 99})
    s = make(t, tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    assert s.failed == 1 and s.planned == 1 and s.problems


def test_requests_respect_rate_limit(tmp_path, clock, fast_settings):
    make(FakeTransport(), tmp_path, clock, fast_settings).ingest_seasons([SEASON])
    # FakeClock only advances via sleep, so every call after the first waits the full interval
    assert len(clock.sleeps) == PER_SEASON - 1 and all(x == pytest.approx(1.0) for x in clock.sleeps)
