"""Project-wide constants and settings. Nothing here is secret."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# Long-term scope. 2019-20 (bubble) and 2020-21 (72 games, March break) are
# flagged so analyses can be run with and without them.
ALL_SEASONS: tuple[str, ...] = (
    "2018-19", "2019-20", "2020-21", "2021-22",
    "2022-23", "2023-24", "2024-25", "2025-26",
)
IRREGULAR_SEASONS = frozenset({"2019-20", "2020-21"})
PHASE1_SEASONS: tuple[str, ...] = ("2022-23", "2023-24")

# Evaluation design (Modified Option A, decided 2026-11-10). Exploratory analysis, hyperparameter
# estimation and model selection may use ONLY the development seasons. The held-out seasons are
# touched once, for final evaluation (2025-26 is never used for training or tuning).
DEV_SEASONS: tuple[str, ...] = ALL_SEASONS[:6]          # 2018-19 .. 2023-24
HELDOUT_SEASONS: tuple[str, ...] = ALL_SEASONS[6:]      # 2024-25 (validation), 2025-26 (final test)

# Phase 0 finding: stats.nba.com dashboard endpoints silently truncate at
# 2,000 rows. A response of this size must be treated as incomplete.
ROW_CAP = 2000
N_TEAMS = 30


@dataclass(frozen=True)
class IngestSettings:
    """Politeness and retry policy for stats.nba.com."""

    min_interval_s: float = 1.0   # minimum gap between HTTP requests
    jitter_s: float = 0.5         # random extra gap, so traffic isn't perfectly periodic
    max_attempts: int = 4         # 1 try + 3 retries
    backoff_base_s: float = 2.0   # retry waits grow ~2s, 4s, 8s ...
    backoff_max_s: float = 60.0
    timeout_s: float = 60.0
