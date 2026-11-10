"""HTTP transport, rate limiting and retries.

The transport is passed in as a parameter (dependency injection) rather than
created inside the pipeline. Tests use a fake transport, so the whole test
suite runs offline. That also matters for CI, because stats.nba.com blocks
many cloud IPs.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any, Protocol

import requests

from ..config import IngestSettings
from .specs import GAMELOG, LINEUPS, PLAYERS, TEAMS, RequestSpec

log = logging.getLogger(__name__)

# Errors worth retrying: network problems, timeouts, HTTP errors, and invalid
# JSON (ValueError covers json.JSONDecodeError). Programming errors such as
# TypeError are NOT retried; they should fail immediately.
RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (requests.RequestException, ConnectionError, TimeoutError, ValueError)


class Transport(Protocol):
    def get(self, spec: RequestSpec) -> dict[str, Any]: ...


class NbaApiTransport:
    """Real transport backed by nba_api endpoint classes."""

    def __init__(self, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    @staticmethod
    def _endpoint_class(endpoint: str):
        from nba_api.stats.endpoints import leaguedashlineups, leaguedashplayerstats, leaguedashteamstats, leaguegamelog

        return {
            GAMELOG: leaguegamelog.LeagueGameLog,
            LINEUPS: leaguedashlineups.LeagueDashLineups,
            PLAYERS: leaguedashplayerstats.LeagueDashPlayerStats,
            TEAMS: leaguedashteamstats.LeagueDashTeamStats,
        }[endpoint]

    def get(self, spec: RequestSpec) -> dict[str, Any]:
        cls = self._endpoint_class(spec.endpoint)
        return cls(**spec.kwargs, timeout=self.timeout_s).get_dict()


class RateLimiter:
    """Enforce a minimum interval (plus random jitter) between calls."""

    def __init__(self, min_interval_s: float, jitter_s: float = 0.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 rng: Callable[[], float] = random.random) -> None:
        self.min_interval_s, self.jitter_s = min_interval_s, jitter_s
        self._clock, self._sleep, self._rng = clock, sleep, rng
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            target = self.min_interval_s + self.jitter_s * self._rng()
            elapsed = self._clock() - self._last
            if elapsed < target:
                self._sleep(target - elapsed)
        self._last = self._clock()


def backoff_delay(attempt: int, base_s: float, max_s: float, rng: Callable[[], float] = random.random) -> float:
    """Exponential backoff with 'equal jitter'.

    For retry n the ceiling is d = min(max_s, base_s * 2**(n-1)), and the wait is
    uniform on [d/2, d]. The jitter keeps many clients from retrying at the same
    moment, and the d/2 floor guarantees a real pause.
    """
    d = min(max_s, base_s * 2 ** (attempt - 1))
    return d / 2 + rng() * d / 2


class FetchFailed(Exception):
    def __init__(self, key: str, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"{key}: failed after {attempts} attempts: {last_error!r}")
        self.key, self.attempts, self.last_error = key, attempts, last_error


def fetch_with_retries(transport: Transport, spec: RequestSpec, settings: IngestSettings, limiter: RateLimiter,
                       sleep: Callable[[float], None] = time.sleep,
                       rng: Callable[[], float] = random.random) -> tuple[dict[str, Any], int]:
    """Return (payload, attempts_used) or raise FetchFailed."""
    last_error: BaseException | None = None
    for attempt in range(1, settings.max_attempts + 1):
        limiter.wait()  # every HTTP call, including retries, is rate limited
        try:
            return transport.get(spec), attempt
        except RETRYABLE_ERRORS as exc:
            last_error = exc
            if attempt < settings.max_attempts:
                delay = backoff_delay(attempt, settings.backoff_base_s, settings.backoff_max_s, rng)
                log.warning("%s: attempt %d failed (%s); retrying in %.1fs", spec.key, attempt, type(exc).__name__, delay)
                sleep(delay)
    assert last_error is not None
    raise FetchFailed(spec.key, settings.max_attempts, last_error)
