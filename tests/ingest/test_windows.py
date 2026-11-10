from datetime import date, timedelta

import pytest

from nba_lineups.ingest.windows import POST, PRE, DateWindow, build_windows, find_all_star_break


def daily(start: date, end: date, skip: tuple[date, date] | None = None) -> list[date]:
    out, d = [], start
    while d <= end:
        if not (skip and skip[0] <= d <= skip[1]):
            out.append(d)
        d += timedelta(days=1)
    return out


def test_february_break_detected():
    dates = daily(date(2023, 10, 24), date(2024, 4, 14), skip=(date(2024, 2, 16), date(2024, 2, 21)))
    assert find_all_star_break(dates, "2023-24") == (date(2024, 2, 15), date(2024, 2, 22))


def test_march_break_detected_like_2020_21():
    dates = daily(date(2020, 12, 22), date(2021, 5, 16), skip=(date(2021, 3, 5), date(2021, 3, 9)))
    assert find_all_star_break(dates, "2020-21") == (date(2021, 3, 4), date(2021, 3, 10))


def test_covid_suspension_is_not_mistaken_for_the_break():
    # Feb break plus the much longer Mar 12 - Jul 29 2020 suspension
    dates = [d for d in daily(date(2019, 10, 22), date(2020, 8, 14), skip=(date(2020, 2, 14), date(2020, 2, 19)))
             if not (date(2020, 3, 12) <= d <= date(2020, 7, 29))]
    assert find_all_star_break(dates, "2019-20") == (date(2020, 2, 13), date(2020, 2, 20))


def test_no_break_raises():
    with pytest.raises(ValueError, match="no All-Star break"):
        find_all_star_break(daily(date(2023, 10, 24), date(2024, 4, 14)), "2023-24")


def test_windows_cover_season_without_overlap():
    dates = daily(date(2023, 10, 24), date(2024, 4, 14), skip=(date(2024, 2, 16), date(2024, 2, 21)))
    w = build_windows("2023-24", dates)
    assert (w[PRE].date_from, w[PRE].date_to) == (date(2023, 10, 24), date(2024, 2, 15))
    assert (w[POST].date_from, w[POST].date_to) == (date(2024, 2, 22), date(2024, 4, 14))
    assert w[PRE].date_to < w[POST].date_from  # features can never see target-window games
    assert w[PRE].nba_from == "10/24/2023"


def test_inverted_window_rejected():
    with pytest.raises(ValueError):
        DateWindow("bad", date(2024, 2, 1), date(2024, 1, 1))
