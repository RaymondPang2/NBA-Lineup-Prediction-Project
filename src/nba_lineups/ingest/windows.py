"""Pre/post All-Star-break date windows.

The break is detected from actual game dates rather than hard-coded, so a
mis-remembered date can't silently shift a window. Every feature must come
from `pre_asb`; the prediction target comes from `post_asb`.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

PRE, POST = "pre_asb", "post_asb"
WINDOW_NAMES = (PRE, POST)
MIN_BREAK_DAYS = 4  # normal schedule gaps are 1-3 days; the break is ~6-7


@dataclass(frozen=True)
class DateWindow:
    name: str
    date_from: date
    date_to: date

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise ValueError(f"{self.name}: date_from {self.date_from} is after date_to {self.date_to}")

    @property
    def nba_from(self) -> str:
        return self.date_from.strftime("%m/%d/%Y")

    @property
    def nba_to(self) -> str:
        return self.date_to.strftime("%m/%d/%Y")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "date_from": self.date_from.isoformat(), "date_to": self.date_to.isoformat()}


def find_all_star_break(game_dates: Iterable[date], season: str) -> tuple[date, date]:
    """Return (last game date before the break, first game date after it).

    Only gaps that start AND end between Feb 1 and Mar 20 of the season's
    second calendar year are considered. That window covers February breaks
    and the March 2021 break, and it excludes the Mar-Jul 2020 COVID suspension
    (which ends in July).
    """
    end_year = int(season[:4]) + 1
    lo, hi = date(end_year, 2, 1), date(end_year, 3, 20)
    days = sorted(set(game_dates))
    gaps = [(b - a, a, b) for a, b in zip(days, days[1:]) if a >= lo and b <= hi]
    if not gaps:
        raise ValueError(f"{season}: no game dates between {lo} and {hi}")
    gap, last_pre, first_post = max(gaps)
    if gap.days < MIN_BREAK_DAYS:
        raise ValueError(f"{season}: largest Feb/Mar gap is {gap.days} days; no All-Star break found")
    return last_pre, first_post


def build_windows(season: str, game_dates: Iterable[date]) -> dict[str, DateWindow]:
    days = sorted(set(game_dates))
    last_pre, first_post = find_all_star_break(days, season)
    return {
        PRE: DateWindow(PRE, days[0], last_pre),
        POST: DateWindow(POST, first_post, days[-1]),
    }
