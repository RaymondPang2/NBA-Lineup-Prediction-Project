"""Chronological validation: expanding-window folds over the development seasons.

Fold k trains on every (included) season BEFORE its validation season and validates on that season,
so no fold ever trains on the future. The held-out seasons (2024-25, 2025-26) can't appear in a fold.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..analysis.data import HeldOutDataError
from ..config import DEV_SEASONS, HELDOUT_SEASONS, IRREGULAR_SEASONS


@dataclass(frozen=True)
class Fold:
    train_seasons: tuple[str, ...]
    val_season: str

    @property
    def name(self) -> str:
        return f"val {self.val_season} (train {self.train_seasons[0]}..{self.train_seasons[-1]}, {len(self.train_seasons)} seasons)"


def expanding_window_folds(seasons=DEV_SEASONS, exclude_irregular: bool = False, min_train: int = 1) -> list[Fold]:
    seasons = list(seasons)
    if set(seasons) & set(HELDOUT_SEASONS) or not set(seasons) <= set(DEV_SEASONS):
        raise HeldOutDataError(f"folds may only use development seasons {list(DEV_SEASONS)}; got {seasons}")
    if seasons != sorted(seasons):
        raise ValueError("seasons must be in chronological order")
    if exclude_irregular:
        seasons = [s for s in seasons if s not in IRREGULAR_SEASONS]
    return [Fold(tuple(seasons[:i]), seasons[i]) for i in range(min_train, len(seasons))]


# Sensitivity design (approved): with and without the irregular 2019-20 (bubble) and 2020-21 (72 games) seasons.
#  all           every development season, validation folds 2019-20 .. 2023-24
#  regular_only  irregular seasons removed from training AND validation (validation 2021-22 .. 2023-24)
# Comparing `regular_only` with `all` restricted to the same validation seasons isolates the effect of
# TRAINING on the irregular seasons.
VARIANTS = {"all": dict(exclude_irregular=False), "regular_only": dict(exclude_irregular=True)}
