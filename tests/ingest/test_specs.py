from datetime import date
from pathlib import Path

from nba_lineups.ingest.specs import LINEUPS, RequestSpec, gamelog_spec, season_specs
from nba_lineups.ingest.windows import POST, PRE, DateWindow

from ..conftest import TEAM_IDS

WINDOWS = {PRE: DateWindow(PRE, date(2023, 10, 24), date(2024, 2, 15)),
           POST: DateWindow(POST, date(2024, 2, 22), date(2024, 4, 14))}


def test_season_plan_size_and_unique_keys():
    specs = season_specs("2023-24", WINDOWS, TEAM_IDS)
    # 2 team + 2 player + (2 windows x 3 measures x 30 teams) lineup requests
    assert len(specs) == 2 + 2 + 180
    assert len({s.key for s in specs}) == len(specs)


def test_lineup_spec_params():
    spec = next(s for s in season_specs("2023-24", WINDOWS, TEAM_IDS)
                if s.endpoint == LINEUPS and s.window == POST and s.measure == "Opponent")
    kw = spec.kwargs
    assert kw["group_quantity"] == 5
    assert kw["per_mode_detailed"] == "Totals"
    assert (kw["date_from_nullable"], kw["date_to_nullable"]) == ("02/22/2024", "04/14/2024")
    assert kw["team_id_nullable"] == spec.team_id
    assert spec.key == f"2023-24/leaguedashlineups/post_asb/opponent/team_{spec.team_id}"


def test_param_order_does_not_change_identity():
    a = RequestSpec.make("x", "2023-24", {"a": 1, "b": 2})
    b = RequestSpec.make("x", "2023-24", {"b": 2, "a": 1})
    assert a == b and hash(a) == hash(b)


def test_cache_path():
    assert gamelog_spec("2022-23").cache_path(Path("raw")) == Path("raw/2022-23/leaguegamelog/league.json")


def test_location_split_specs_are_disjoint_from_the_season_plan():
    from nba_lineups.ingest.specs import location_split_specs
    splits = location_split_specs("2023-24", WINDOWS[PRE], TEAM_IDS)
    assert len(splits) == 2 * 3 * 30                     # location x measure x team
    assert {s.kwargs["location_nullable"] for s in splits} == {"Home", "Road"}
    assert all(s.window == PRE and s.kwargs["date_to_nullable"] == "02/15/2024" for s in splits)
    keys = {s.key for s in splits}
    assert len(keys) == len(splits)
    assert not keys & {s.key for s in season_specs("2023-24", WINDOWS, TEAM_IDS)}   # existing cache untouched
    home = next(s for s in splits if s.split == "home" and s.measure == "Base")
    assert home.key == f"2023-24/leaguedashlineups/pre_asb/home/base/team_{home.team_id}"
