import copy
from datetime import date

import pytest

from nba_lineups.ingest.specs import gamelog_spec, season_specs
from nba_lineups.ingest.validate import validate_payload
from nba_lineups.ingest.windows import POST, PRE, DateWindow

from ..conftest import TEAM_IDS, synthetic_payload

WINDOWS = {PRE: DateWindow(PRE, date(2023, 10, 24), date(2024, 2, 15)),
           POST: DateWindow(POST, date(2024, 2, 22), date(2024, 4, 14))}
SPECS = season_specs("2023-24", WINDOWS, TEAM_IDS)


def spec_for(endpoint, measure="Advanced"):
    return next(s for s in SPECS if s.endpoint == endpoint and s.measure == measure)


def rows(payload):
    return payload["resultSets"][0]["rowSet"]


def col(payload, name):
    return payload["resultSets"][0]["headers"].index(name)


@pytest.mark.parametrize("spec", [gamelog_spec("2023-24")] + [spec_for("leaguedashlineups", m) for m in
                                                               ("Advanced", "Base", "Opponent")]
                         + [spec_for("leaguedashplayerstats"), spec_for("leaguedashteamstats")],
                         ids=lambda s: s.key.split("/", 1)[1])
def test_valid_synthetic_payloads_pass(spec):
    report = validate_payload(spec, synthetic_payload(spec))
    assert report.ok, report.errors


@pytest.fixture
def lineup():
    spec = spec_for("leaguedashlineups")
    return spec, synthetic_payload(spec)


def test_row_cap_is_rejected(lineup):
    spec, p = lineup
    p["resultSets"][0]["rowSet"] = [copy.deepcopy(rows(p)[0]) for _ in range(2000)]
    for i, r in enumerate(rows(p)):  # unique ids so ONLY the cap rule can fire
        r[col(p, "GROUP_ID")] = "-" + "-".join(str(i * 10 + k) for k in range(5)) + "-"
    report = validate_payload(spec, p)
    assert any("truncated" in e for e in report.errors)


@pytest.mark.parametrize("group_id,message", [
    ("-1-2-3-4-", "exactly 5"),
    ("-5-4-3-2-1-", "numeric order"),
    ("-1-1-2-3-4-", "repeated player"),
    ("-1-2-x-4-5-", "non-numeric"),
])
def test_bad_group_ids(lineup, group_id, message):
    spec, p = lineup
    rows(p)[0][col(p, "GROUP_ID")] = group_id
    assert any(message in e for e in validate_payload(spec, p).errors)


def test_string_sorted_ids_are_rejected(lineup):
    # Sorted as strings ("1000" < "999") but not numerically: Phase 0 showed NBA sorts numerically.
    spec, p = lineup
    rows(p)[0][col(p, "GROUP_ID")] = "-1000-1001-1002-1003-999-"
    assert any("numeric order" in e for e in validate_payload(spec, p).errors)


def test_duplicate_lineup_and_wrong_team(lineup):
    spec, p = lineup
    rows(p)[1] = list(rows(p)[0])
    rows(p)[2][col(p, "TEAM_ID")] = 1
    errors = validate_payload(spec, p).errors
    assert any("duplicate" in e for e in errors) and any("other than" in e for e in errors)


def test_name_variant_split_is_a_warning(lineup):
    # Same 5 player ids, different display name (seen for real: 'L. Doncic' vs 'L. Dončić', 2018-19)
    spec, p = lineup
    rows(p)[1] = list(rows(p)[0])
    rows(p)[1][col(p, "GROUP_NAME")] = rows(p)[0][col(p, "GROUP_NAME")] + " Sr."
    report = validate_payload(spec, p)
    assert report.ok and any("name variants" in w for w in report.warnings)


def test_missing_column_and_malformed(lineup):
    spec, p = lineup
    p["resultSets"][0]["headers"][col(p, "POSS")] = "POSSESSIONS"
    assert any("missing required columns" in e for e in validate_payload(spec, p).errors)
    assert not validate_payload(spec, {"oops": 1}).ok


def test_filter_echo_mismatch_is_rejected(lineup):
    spec, p = lineup
    p["parameters"]["DateTo"] = "04/14/2024"  # server ignored our pre-break DateTo -> leakage risk
    assert any("DateTo" in e for e in validate_payload(spec, p).errors)


def test_zero_possessions_is_a_warning_not_an_error(lineup):
    spec, p = lineup
    rows(p)[0][col(p, "POSS")] = 0
    report = validate_payload(spec, p)
    assert report.ok and any("POSS == 0" in w for w in report.warnings)


def test_empty_lineups_rejected(lineup):
    spec, p = lineup
    p["resultSets"][0]["rowSet"] = []
    assert not validate_payload(spec, p).ok


def test_team_table_needs_30_teams():
    spec = spec_for("leaguedashteamstats")
    p = synthetic_payload(spec)
    p["resultSets"][0]["rowSet"].pop()
    assert any("30 unique teams" in e for e in validate_payload(spec, p).errors)


def test_gamelog_needs_two_rows_per_game():
    spec = gamelog_spec("2023-24")
    p = synthetic_payload(spec)
    p["resultSets"][0]["rowSet"].pop()
    assert any("exactly 2 team rows" in e for e in validate_payload(spec, p).errors)
