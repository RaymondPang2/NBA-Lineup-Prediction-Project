"""The Power BI Project, semantic model and DAX: structure, consistency and the analytical contract.

No database and no Power BI needed. Power BI's engines don't run on macOS, so these tests check everything
that can be checked statically: the committed files equal a fresh generation from model.py / report.py, every
report file validates against Microsoft's published PBIR JSON schemas (vendored in tests/powerbi/schemas),
every field and DAX reference resolves, and the relationship graph has exactly one filter path per pair.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from nba_lineups.bi import model as bim
from nba_lineups.bi import project
from nba_lineups.bi import report as rp
from nba_lineups.config import HELDOUT_SEASONS, PROJECT_ROOT

SCHEMAS = Path(__file__).parent / "schemas"
MS = "https://developer.microsoft.com/json-schemas/"
TABLES = {t.name: t for t in bim.TABLES}
MEASURES = {m.name: m for m in bim.MEASURES}


# ------------------------------------------------------------------------------------------------ generation

def test_committed_project_is_up_to_date(tmp_path):
    """powerbi/ must be exactly what the generator produces (run scripts/phase9/build_powerbi_project.py)."""
    fresh = {p.relative_to(tmp_path): p.read_bytes() for p in project.build(tmp_path)}
    committed = PROJECT_ROOT / "powerbi"
    for rel, content in fresh.items():
        assert (committed / rel).read_bytes() == content, f"powerbi/{rel} is stale: regenerate the project"
    generated_dirs = [committed / f"{project.NAME}.SemanticModel", committed / f"{project.NAME}.Report"]
    extra = {p.relative_to(committed) for d in generated_dirs for p in d.rglob("*") if p.is_file()} - set(fresh)
    assert not extra, f"files not produced by the generator: {sorted(map(str, extra))}"


def test_reference_docs_are_up_to_date():
    assert project.DOCS.read_text() == project.reference_markdown() + "\n", "regenerate docs/powerbi_reference.md"


def test_generation_is_deterministic(tmp_path):
    a = {p.relative_to(tmp_path / "a"): p.read_bytes() for p in project.build(tmp_path / "a")}
    b = {p.relative_to(tmp_path / "b"): p.read_bytes() for p in project.build(tmp_path / "b")}
    assert a == b


# ------------------------------------------------------------------------------------------------ PBIR schemas

@pytest.fixture(scope="module")
def registry() -> Registry:
    resources = []
    for p in SCHEMAS.rglob("*.json"):
        url = MS + p.relative_to(SCHEMAS).as_posix()
        resources.append((url, Resource.from_contents(json.loads(p.read_text()), default_specification=DRAFT7)))
    return Registry().with_resources(resources)


def report_json_files() -> list[Path]:
    rd = PROJECT_ROOT / "powerbi" / f"{project.NAME}.Report"
    return sorted([rd / "definition.pbir", *(rd / "definition").rglob("*.json")])


@pytest.mark.parametrize("path", report_json_files(), ids=lambda p: p.relative_to(PROJECT_ROOT / "powerbi").as_posix())
def test_report_files_validate_against_microsoft_schemas(path, registry):
    doc = json.loads(path.read_text())
    url = doc["$schema"]
    schema = registry.contents(url)
    errors = sorted(Draft7Validator(schema, registry=registry).iter_errors(doc), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message[:200]}" for e in errors[:5])


def test_semantic_model_definition_file_validates(registry):
    doc = json.loads((PROJECT_ROOT / "powerbi" / f"{project.NAME}.SemanticModel" / "definition.pbism").read_text())
    errors = list(Draft7Validator(registry.contents(doc["$schema"]), registry=registry).iter_errors(doc))
    assert not errors, errors[0].message


def test_report_has_the_five_required_pages():
    assert [p.display_name for p in rp.PAGES] == ["1 Team Overview", "2 Lineup Analysis", "3 Statistical Reliability",
                                                   "4 Model Performance", "5 Selection Bias"]
    for p in rp.PAGES:
        names = [v.name for v in p.visuals]
        assert len(names) == len(set(names)), f"{p.name}: duplicate visual names"
        assert any(v.type == "slicer" for v in p.visuals), f"{p.name} has no slicer"
        for v in p.visuals:
            assert 0 <= v.x and v.x + v.w <= 1280 and 0 <= v.y and v.y + v.h <= 720, f"{p.name}/{v.name} is off the canvas"
            assert v.type == "textbox" or v.title, f"{p.name}/{v.name} needs a readable title"


def test_visuals_do_not_overlap():
    for p in rp.PAGES:
        boxes = [(v.name, v.x, v.y, v.x + v.w, v.y + v.h) for v in p.visuals]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap = min(a[3], b[3]) > max(a[1], b[1]) and min(a[4], b[4]) > max(a[2], b[2])
                assert not overlap, f"{p.name}: {a[0]} overlaps {b[0]}"


def test_every_report_field_exists_in_the_model():
    for f in rp.all_fields():
        if f[0] == "measure":
            assert f[1] in MEASURES, f"unknown measure {f[1]}"
        else:
            assert f[1] in TABLES and f[2] in {c.name for c in TABLES[f[1]].columns}, f"unknown column {f[1]}[{f[2]}]"


# ------------------------------------------------------------------------------------------------ DAX lint

REF_COL = re.compile(r"(?:'([^']+)'|\b([A-Za-z_][A-Za-z0-9_]*))\[([^\]]+)\]")
REF_MEASURE = re.compile(r"(?<![\w'\]])\[([^\]]+)\]")


def _strip_strings(expr: str) -> str:
    return re.sub(r'"[^"]*"', '""', expr)


def test_dax_references_resolve():
    for m in bim.MEASURES:
        expr = _strip_strings(m.expression)
        local = set(re.findall(r'"(@[^"]+)"', m.expression))     # ADDCOLUMNS names
        for qt, t, c in REF_COL.findall(expr):
            table = qt or t
            assert table in TABLES, f"{m.name}: unknown table {table}"
            assert c in {x.name for x in TABLES[table].columns}, f"{m.name}: unknown column {table}[{c}]"
        no_cols = REF_COL.sub("", expr)
        for ref in REF_MEASURE.findall(no_cols):
            assert ref in MEASURES or ref in local, f"{m.name}: unknown measure [{ref}]"


def test_dax_is_balanced_and_acyclic():
    deps = {}
    for m in bim.MEASURES:
        e = _strip_strings(m.expression)
        assert e.count("(") == e.count(")"), f"{m.name}: unbalanced parentheses"
        deps[m.name] = {r for r in REF_MEASURE.findall(REF_COL.sub("", e)) if r in MEASURES}
    state: dict[str, int] = {}

    def visit(n, stack=()):
        assert state.get(n) != 1, f"measure cycle: {' → '.join(stack + (n,))}"
        if state.get(n) == 2:
            return
        state[n] = 1
        for d in deps[n]:
            visit(d, stack + (n,))
        state[n] = 2

    for n in deps:
        visit(n)


def test_measure_names_unique_and_documented():
    assert len(MEASURES) == len(bim.MEASURES)
    for m in bim.MEASURES:
        assert m.description and m.folder and m.format


def test_measures_dax_script_defines_every_measure():
    dax = (PROJECT_ROOT / "powerbi" / "measures.dax").read_text()
    for m in bim.MEASURES:
        assert f"MEASURE '_Measures'[{m.name}] =" in dax


@pytest.mark.parametrize("name", ["ORtg", "DRtg"])
def test_ratings_aggregate_first_then_divide(name):
    e = MEASURES[name].expression
    assert e.startswith("DIVIDE ( SUM (") and "AVERAGE" not in e
    assert "opp_pts_rated" in MEASURES["DRtg"].expression and "opp_poss" in MEASURES["DRtg"].expression


def test_net_rating_is_blank_unless_both_ratings_exist():
    assert "NOT ISBLANK ( o ) && NOT ISBLANK ( d )" in MEASURES["Net Rating"].expression


def test_model_measures_use_the_evaluation_sample_and_possession_weights():
    for n in ["Model RMSE", "Team Prior RMSE", "League Mean RMSE", "Model MAE", "Noise Floor RMSE", "Mean Observed"]:
        e = MEASURES[n].expression
        assert "in_evaluation_sample] = 1" in e and "[post_poss]" in e, n


# ------------------------------------------------------------------------------------------------ relationships

def test_relationship_columns_exist():
    for r in bim.RELATIONSHIPS:
        assert r.from_column in {c.name for c in TABLES[r.from_table].columns}
        assert r.to_column in {c.name for c in TABLES[r.to_table].columns}
        assert TABLES[r.from_table].column(r.from_column).dtype == TABLES[r.to_table].column(r.to_column).dtype


def _filter_edges():
    """Directed edges along which a filter propagates (one side → many side, plus reverse when bidirectional)."""
    edges = defaultdict(set)
    for r in bim.RELATIONSHIPS:
        edges[r.to_table].add(r.from_table)
        if r.both_directions:
            edges[r.from_table].add(r.to_table)
    return edges


def _paths(edges, src, dst, seen=()):
    if src == dst:
        return 1
    return sum(_paths(edges, n, dst, seen + (src,)) for n in edges[src] if n not in seen + (src,))


def test_exactly_one_filter_path_from_each_dimension_to_each_fact():
    edges = _filter_edges()
    facts = ["fact_lineup_window", "fact_prediction", "fact_team_window"]
    for dim in ["dim_season", "dim_team", "dim_window", "dim_player", "dim_lineup"]:
        for fact in facts:
            assert _paths(edges, dim, fact) <= 1, f"ambiguous: {dim} reaches {fact} by several paths"
    assert _paths(edges, "dim_player", "fact_lineup_window") == 1      # player → bridge → lineup → fact
    assert _paths(edges, "dim_player", "fact_prediction") == 1
    assert _paths(edges, "dim_lineup", "dim_season") == 0            # no back-door season path through lineups


def test_only_the_bridge_is_bidirectional():
    both = [r for r in bim.RELATIONSHIPS if r.both_directions]
    assert [(r.from_table, r.to_table) for r in both] == [("bridge_lineup_player", "dim_lineup")]


# ------------------------------------------------------------------------------------------------ SQL and contract

def test_sql_held_out_seasons_match_config():
    sql = (PROJECT_ROOT / "sql" / "powerbi" / "bi_views.sql").read_text()
    listed = re.search(r"season_id IN \(([^)]*)\) THEN 'Held-out'", sql).group(1)
    assert sorted(re.findall(r"'([^']+)'", listed)) == sorted(HELDOUT_SEASONS)


def test_views_store_totals_not_ratings():
    sql = (PROJECT_ROOT / "sql" / "powerbi" / "bi_views.sql").read_text()
    fact = sql[sql.index("CREATE VIEW bi.fact_lineup_window"):sql.index("CREATE VIEW bi.fact_team_window")]
    assert "rating" not in fact.lower().replace("v_lineup_window_ratings", "")


def test_prediction_table_has_no_post_break_input_columns():
    """fact_prediction carries the OUTCOME (observed_post_net, post_poss) but every prediction column was scored
    by FrozenPredictor from pre-break tables; the export joins the outcome after scoring."""
    src = (PROJECT_ROOT / "src" / "nba_lineups" / "bi" / "export.py").read_text()
    scoring = src[src.index("def predictions("):src.index("# The OUTCOME")]
    assert "post_asb" not in scoring and "observed" not in scoring
    assert "predictor.season(conn, season).frame" in scoring
