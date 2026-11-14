"""Access control for the held-out seasons (2024-25, 2025-26).

Every loader refuses held-out seasons unless it is handed a HoldoutKey. A key can only be minted by
`holdout.unlock`, which first verifies that the final model specification and artifact are FROZEN
(written, hashed and committed to git). This turns "don't touch the test set until the model is
frozen" from a promise into a precondition the code enforces.
"""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from ..analysis.data import HeldOutDataError
from ..config import ALL_SEASONS, DEV_SEASONS

_MINT = object()   # private token: only code that imports it deliberately can construct a key


class HoldoutKey:
    __slots__ = ("spec_sha256",)

    def __init__(self, token: object, spec_sha256: str) -> None:
        if token is not _MINT:
            raise HeldOutDataError("a HoldoutKey can only be issued by holdout.unlock() after the model is frozen")
        self.spec_sha256 = spec_sha256


def allowed_seasons(key: HoldoutKey | None) -> tuple[str, ...]:
    return ALL_SEASONS if isinstance(key, HoldoutKey) else DEV_SEASONS


def check_seasons(seasons: Iterable[str], key: HoldoutKey | None = None) -> list[str]:
    s = list(seasons)
    bad = sorted(set(s) - set(allowed_seasons(key)))
    if bad:
        raise HeldOutDataError(f"refused {bad}: held-out seasons need a HoldoutKey (frozen model); "
                               f"development seasons are {list(DEV_SEASONS)}")
    return s


def require_allowed(df: pd.DataFrame, key: HoldoutKey | None = None, column: str = "season_id") -> pd.DataFrame:
    check_seasons(df[column].unique(), key)
    return df
