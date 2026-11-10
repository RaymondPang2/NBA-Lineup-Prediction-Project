import pytest

from nba_lineups.ingest.client import FetchFailed, RateLimiter, backoff_delay, fetch_with_retries
from nba_lineups.ingest.specs import gamelog_spec

from ..conftest import FakeTransport


def test_rate_limiter_waits_only_the_remaining_interval(clock):
    rl = RateLimiter(1.0, jitter_s=0.0, clock=clock, sleep=clock.sleep)
    rl.wait()                # first call: no wait
    clock.now += 0.3         # 0.3s of "work"
    rl.wait()                # must wait the remaining 0.7s
    clock.now += 5.0         # long gap
    rl.wait()                # no wait needed
    assert clock.sleeps == [pytest.approx(0.7)]


def test_rate_limiter_adds_jitter(clock):
    rl = RateLimiter(1.0, jitter_s=0.5, clock=clock, sleep=clock.sleep, rng=lambda: 1.0)
    rl.wait()
    rl.wait()
    assert clock.sleeps == [pytest.approx(1.5)]


@pytest.mark.parametrize("attempt,lo,hi", [(1, 1, 2), (2, 2, 4), (3, 4, 8), (10, 30, 60)])
def test_backoff_bounds(attempt, lo, hi):
    assert backoff_delay(attempt, 2.0, 60.0, rng=lambda: 0.0) == pytest.approx(lo)
    assert backoff_delay(attempt, 2.0, 60.0, rng=lambda: 1.0) == pytest.approx(hi)


def test_retries_then_succeeds(clock, fast_settings):
    spec = gamelog_spec("2023-24")
    transport = FakeTransport(fail_times={spec.key: 2})
    rl = RateLimiter(fast_settings.min_interval_s, 0.0, clock, clock.sleep)
    payload, attempts = fetch_with_retries(transport, spec, fast_settings, rl, clock.sleep, rng=lambda: 0.0)
    assert attempts == 3 and "resultSets" in payload
    assert len(transport.calls) == 3


def test_gives_up_after_max_attempts(clock, fast_settings):
    spec = gamelog_spec("2023-24")
    transport = FakeTransport(fail_times={spec.key: 99}, error=TimeoutError)
    rl = RateLimiter(0.0, 0.0, clock, clock.sleep)
    with pytest.raises(FetchFailed) as exc:
        fetch_with_retries(transport, spec, fast_settings, rl, clock.sleep, rng=lambda: 0.0)
    assert exc.value.attempts == fast_settings.max_attempts
    assert isinstance(exc.value.last_error, TimeoutError)
    assert clock.sleeps == [pytest.approx(1.0), pytest.approx(2.0)]  # backoff between the 3 attempts


def test_programming_errors_are_not_retried(clock, fast_settings):
    spec = gamelog_spec("2023-24")
    transport = FakeTransport(fail_times={spec.key: 1}, error=TypeError)
    rl = RateLimiter(0.0, 0.0, clock, clock.sleep)
    with pytest.raises(TypeError):
        fetch_with_retries(transport, spec, fast_settings, rl, clock.sleep)
    assert len(transport.calls) == 1
