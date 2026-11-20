"""Generate the Power BI Project (PBIP): TMDL semantic model + PBIR report, the theme, and the DAX script.

    powerbi/LineupLab.pbip                         open in Power BI Desktop (Windows)
    powerbi/LineupLab.SemanticModel/definition/    TMDL: tables, CSV partitions, relationships, measures
    powerbi/LineupLab.Report/definition/           PBIR: five pages of visuals
    powerbi/LineupLab.theme.json                   report theme (Lineup Lab palette)
    powerbi/measures.dax                           every measure as one DAX query (browser: DAX query view)

Deterministic: ids are UUID5 of object names, so regenerating produces identical files.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from ..config import PROJECT_ROOT
from . import model as bim
from . import report as rp

OUT = PROJECT_ROOT / "powerbi"
NAME = "LineupLab"
NS = uuid.UUID("6f1c2a52-6a0b-4f0e-9a0e-9b8b0d3c9a11")
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
VERSIONS = {"report": "3.0.0", "page": "2.0.0", "pagesMetadata": "1.0.0", "versionMetadata": "1.0.0", "visualContainer": "2.4.0"}
DEFAULT_DATA_FOLDER = "C:\\LineupLab\\csv\\"

THEME = {
    "name": "Lineup Lab",
    "dataColors": ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"],
    "foreground": "#0B0B0B", "foregroundNeutralSecondary": "#52514E", "foregroundNeutralTertiary": "#898781",
    "background": "#FFFFFF", "backgroundLight": "#F6F6F3", "backgroundNeutral": "#E1E0D9",
    "tableAccent": "#2A78D6", "good": "#006300", "neutral": "#898781", "bad": "#D03B3B",
    "maximum": "#1C5CAB", "center": "#F0EFEC", "minimum": "#E34948",
    "textClasses": {
        "title": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": "#0B0B0B"},
        "header": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": "#0B0B0B"},
        "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": "#52514E"},
        "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 24, "color": "#0B0B0B"},
    },
    "visualStyles": {"*": {"*": {
        "border": [{"show": True, "color": {"solid": {"color": "#E1E0D9"}}, "radius": 8}],
        "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}}],
    }}, "page": {"*": {"background": [{"color": {"solid": {"color": "#F6F6F3"}}, "transparency": 0}]}}},
}


def _id(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def _q(name: str) -> str:
    """TMDL / DAX object name, quoted when needed."""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


def _dax_table(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _desc(text: str, indent: str) -> str:
    return "".join(f"{indent}/// {line}\n" for line in text.splitlines()) if text else ""


# ------------------------------------------------------------------------------------------------ TMDL

M_TYPES = {"int64": "Int64.Type", "double": "type number", "string": "type text", "dateTime": "type date"}


def _partition(t: bim.Table) -> str:
    if t.source == "measures":
        src = '#table(type table [_ = text], {{"measures"}})'
        return f"\tpartition {_q(t.name)} = m\n\t\tmode: import\n\t\tsource = {src}\n"
    types = ", ".join(f'{{"{c.name}", {M_TYPES[c.dtype]}}}' for c in t.columns)
    lines = [
        "let",
        f'    Source = Csv.Document(File.Contents(DataFolder & "{t.name}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f'    Typed = Table.TransformColumnTypes(Headers, {{{types}}}, "en-US")',
        "in",
        "    Typed",
    ]
    body = "".join(f"\t\t\t\t{line}\n" for line in lines)
    return f"\tpartition {_q(t.name)} = m\n\t\tmode: import\n\t\tsource =\n{body}"


def _column(t: bim.Table, c: bim.Column) -> str:
    fmt = c.format or {"int64": "0", "dateTime": "yyyy-mm-dd"}.get(c.dtype)
    out = _desc(c.description, "\t") + f"\tcolumn {_q(c.name)}\n\t\tdataType: {c.dtype}\n"
    if fmt:
        out += f"\t\tformatString: {fmt}\n"
    if c.hidden or t.source == "measures":
        out += "\t\tisHidden\n"
    out += f"\t\tlineageTag: {_id(t.name, c.name)}\n\t\tsummarizeBy: none\n\t\tsourceColumn: {c.name}\n"
    if c.sort_by:
        out += f"\t\tsortByColumn: {_q(c.sort_by)}\n"
    return out + "\n"


def _measure(m: bim.Measure) -> str:
    lines = m.expression.splitlines()
    head = _desc(m.description, "\t") + f"\tmeasure {_q(m.name)} ="
    if len(lines) == 1:
        head += f" {lines[0]}\n"
    else:
        head += "\n" + "".join(f"\t\t\t{line}\n" for line in lines)
    return head + (f"\t\tformatString: {m.format}\n\t\tdisplayFolder: {m.folder}\n"
                   f"\t\tlineageTag: {_id('measure', m.name)}\n\n")


def table_tmdl(t: bim.Table) -> str:
    out = _desc(t.description, "") + f"table {_q(t.name)}\n\tlineageTag: {_id(t.name)}\n"
    if t.source == "measures":
        out += "\n"
        for m in bim.MEASURES:
            out += _measure(m)
    else:
        out += "\n"
    for c in t.columns:
        out += _column(t, c)
    return out + _partition(t)


def model_tmdl() -> str:
    refs = "".join(f"ref table {_q(t.name)}\n" for t in bim.TABLES)
    return ("model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
            "\tdiscourageImplicitMeasures\n\tsourceQueryCulture: en-US\n\n"
            "annotation PBI_QueryOrder = " + json.dumps(["DataFolder"] + [t.name for t in bim.TABLES]) + "\n\n" + refs)


def relationships_tmdl() -> str:
    out = ""
    for r in bim.RELATIONSHIPS:
        out += (f"relationship {_id('rel', r.from_table, r.from_column, r.to_table)}\n"
                + ("\tcrossFilteringBehavior: bothDirections\n" if r.both_directions else "")
                + f"\tfromColumn: {_q(r.from_table)}.{_q(r.from_column)}\n\ttoColumn: {_q(r.to_table)}.{_q(r.to_column)}\n\n")
    return out


def expressions_tmdl(folder: str = DEFAULT_DATA_FOLDER) -> str:
    return ("/// Folder holding the exported CSVs (data/powerbi/csv/ from scripts/phase9/export_powerbi.py), with a trailing backslash.\n"
            f'expression DataFolder = "{folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
            f"\tlineageTag: {_id('DataFolder')}\n\n\tannotation PBI_ResultType = Text\n")


# ------------------------------------------------------------------------------------------------ PBIR

def _field(f: rp.Field) -> dict:
    if f[0] == "measure":
        return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": f[1]}}
    return {"Column": {"Expression": {"SourceRef": {"Entity": f[1]}}, "Property": f[2]}}


def _ref(f: rp.Field) -> tuple[str, str]:
    return (f"_Measures.{f[1]}", f[1]) if f[0] == "measure" else (f"{f[1]}.{f[2]}", f[2])


def _lit(value) -> dict:
    v = ("'" + value.replace("'", "''") + "'") if isinstance(value, str) else ("true" if value is True else "false" if value is False else str(value))
    return {"expr": {"Literal": {"Value": v}}}


def visual_json(v: rp.Visual, z: int) -> dict:
    container = {"$schema": f"{SCHEMA}/visualContainer/{VERSIONS['visualContainer']}/schema.json", "name": v.name,
                 "position": {"x": v.x, "y": v.y, "z": z * 1000, "width": v.w, "height": v.h, "tabOrder": z * 1000}}
    visual: dict = {"visualType": v.type}
    if v.type == "textbox":
        paras = [{"textRuns": [{"value": v.text[0], "textStyle": {"fontWeight": "bold", "fontSize": "18pt"}}]}]
        paras += [{"textRuns": [{"value": t, "textStyle": {"fontSize": "10pt"}}]} for t in v.text[1:]]
        visual["objects"] = {"general": [{"properties": {"paragraphs": paras}}]}
    else:
        state = {}
        for role, fields in v.roles.items():
            projs = []
            for f in fields:
                q, n = _ref(f)
                projs.append({"field": _field(f), "queryRef": q, "nativeQueryRef": n})
            state[role] = {"projections": projs}
        visual["query"] = {"queryState": state}
        if v.sort:
            visual["query"]["sortDefinition"] = {"sort": [{"field": _field(v.sort[0]), "direction": v.sort[1]}], "isDefaultSort": False}
        objects = {}
        if v.type == "slicer":
            objects["data"] = [{"properties": {"mode": _lit("Dropdown" if v.dropdown else "Basic")}}]
            if v.searchable:
                objects["general"] = [{"properties": {"selfFilterEnabled": _lit(True)}}]
        if objects:
            visual["objects"] = objects
        if v.title:
            visual["visualContainerObjects"] = {"title": [{"properties": {"show": _lit(True), "text": _lit(v.title)}}]}
    container["visual"] = visual
    return container


def report_files() -> dict[str, dict]:
    files: dict[str, dict] = {
        "definition/version.json": {"$schema": f"{SCHEMA}/versionMetadata/{VERSIONS['versionMetadata']}/schema.json", "version": "2.0.0"},
        "definition/report.json": {
            "$schema": f"{SCHEMA}/report/{VERSIONS['report']}/schema.json",
            "themeCollection": {
                "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": {"visual": "1.8.50", "report": "2.0.50", "page": "1.3.50"},
                              "type": "SharedResources"},
                "customTheme": {"name": f"{NAME}.json", "reportVersionAtImport": {"visual": "1.8.50", "report": "2.0.50", "page": "1.3.50"},
                                "type": "RegisteredResources"}},
            "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                                  "items": [{"name": f"{NAME}.json", "path": f"{NAME}.json", "type": "CustomTheme"}]}],
            "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True},
        },
        "definition/pages/pages.json": {"$schema": f"{SCHEMA}/pagesMetadata/{VERSIONS['pagesMetadata']}/schema.json",
                                        "pageOrder": [p.name for p in rp.PAGES], "activePageName": rp.PAGES[0].name},
    }
    for p in rp.PAGES:
        files[f"definition/pages/{p.name}/page.json"] = {
            "$schema": f"{SCHEMA}/page/{VERSIONS['page']}/schema.json", "name": p.name, "displayName": p.display_name,
            "displayOption": "FitToPage", "height": 720, "width": 1280}
        for z, v in enumerate(p.visuals):
            files[f"definition/pages/{p.name}/visuals/{v.name}/visual.json"] = visual_json(v, z)
    return files


# ------------------------------------------------------------------------------------------------ DAX script

def measures_dax() -> str:
    """One DAX query that defines every measure. In the Power BI Service: open the semantic model → DAX query view
    → paste → Run → 'Update model with changes' adds all measures to the _Measures table at once."""
    body = ""
    for m in bim.MEASURES:
        expr = m.expression.replace("\n", "\n\t\t")
        body += f"\t-- {m.folder} · {m.description}\n\tMEASURE {_dax_table('_Measures')}[{m.name}] =\n\t\t{expr}\n\n"
    return ("// Lineup Lab · every measure of the semantic model (generated from src/nba_lineups/bi/model.py).\n"
            "// Power BI Service: semantic model → Open data model / DAX query view → paste → Run →\n"
            "// 'Update model with changes'. Then set each measure's format string as listed in docs/powerbi.md.\n"
            "DEFINE\n" + body + "EVALUATE\n\tROW ( \"Net Rating\", [Net Rating], \"Model RMSE\", [Model RMSE] )\n")


# ------------------------------------------------------------------------------------------------ write

def _write(path: Path, content: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(content, indent=2, ensure_ascii=False) + "\n" if isinstance(content, dict) else content
    path.write_text(text, encoding="utf-8", newline="\n")


def build(out: Path = OUT) -> list[Path]:
    sm, rd = out / f"{NAME}.SemanticModel", out / f"{NAME}.Report"
    for d in (sm, rd):
        if d.exists():
            shutil.rmtree(d)
    written: dict[Path, str | dict] = {
        out / f"{NAME}.pbip": {"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                               "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                               "settings": {"enableAutoRecovery": True}},
        sm / "definition.pbism": {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                  "version": "4.2", "settings": {}},
        sm / ".platform": {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                           "metadata": {"type": "SemanticModel", "displayName": NAME},
                           "config": {"version": "2.0", "logicalId": _id("semanticModel")}},
        sm / "definition/database.tmdl": "database\n\tcompatibilityLevel: 1567\n",
        sm / "definition/model.tmdl": model_tmdl(),
        sm / "definition/expressions.tmdl": expressions_tmdl(),
        sm / "definition/relationships.tmdl": relationships_tmdl(),
        rd / "definition.pbir": {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                                 "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}},
        rd / ".platform": {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                           "metadata": {"type": "Report", "displayName": NAME}, "config": {"version": "2.0", "logicalId": _id("report")}},
        rd / f"StaticResources/RegisteredResources/{NAME}.json": THEME,
        out / f"{NAME}.theme.json": THEME,
        out / "measures.dax": measures_dax(),
    }
    for t in bim.TABLES:
        written[sm / f"definition/tables/{t.name}.tmdl"] = table_tmdl(t)
    for rel, content in report_files().items():
        written[rd / rel] = content
    for p, c in written.items():
        _write(p, c)
    return sorted(written)


def write_docs() -> Path:
    _write(DOCS, reference_markdown() + "\n")
    return DOCS


# ------------------------------------------------------------------------------------------------ docs

DOCS = PROJECT_ROOT / "docs" / "powerbi_reference.md"


def reference_markdown() -> str:
    """Tables, relationships, measures and page layouts, generated from model.py and report.py."""
    out = ["# Power BI semantic model reference", "",
           "Generated by `scripts/phase9/build_powerbi_project.py` from `src/nba_lineups/bi/model.py` and `report.py`. "
           "Do not edit by hand. The guide is [docs/powerbi.md](powerbi.md).", "", "## Tables", ""]
    out += ["| Table | Rows come from | Description |", "|---|---|---|"]
    src = {"sql": "SQL view `bi.{}`", "python": "export script (frozen model)", "measures": "none (holds measures)"}
    for t in bim.TABLES:
        out.append(f"| `{t.name}` | {src[t.source].format(t.name)} | {t.description} |")
    out += ["", "### Columns", ""]
    for t in bim.TABLES:
        if t.source == "measures":
            continue
        out += [f"**{t.name}**", "", "| Column | Type | Hidden | Description |", "|---|---|---|---|"]
        out += [f"| `{c.name}` | {c.dtype}{' (may be blank)' if c.nullable else ''} | {'yes' if c.hidden else ''} | {c.description} |" for c in t.columns]
        out.append("")
    out += ["## Relationships", "", "All are many-to-one; only the bridge filters in both directions.", "",
            "| From (many) | To (one) | Cross-filter |", "|---|---|---|"]
    out += [f"| `{r.from_table}[{r.from_column}]` | `{r.to_table}[{r.to_column}]` | {'both' if r.both_directions else 'single'} |"
            for r in bim.RELATIONSHIPS]
    out += ["", f"## Measures ({len(bim.MEASURES)})", "", "All measures live in the `_Measures` table.", ""]
    for folder in sorted({m.folder for m in bim.MEASURES}):
        out += [f"### {folder}", ""]
        for m in (x for x in bim.MEASURES if x.folder == folder):
            out += [f"**{m.name}** · format `{m.format}`  ", m.description, "", "```dax", m.expression, "```", ""]
    out += ["## Report pages", "", "Canvas 1280 × 720. Positions in pixels (x, y, width, height).", ""]
    for p in rp.PAGES:
        out += [f"### {p.display_name}", "", p.purpose, "", "| Visual | Type | Position | Fields |", "|---|---|---|---|"]
        for v in p.visuals:
            fields = "; ".join(f"{role}: " + ", ".join(f"[{f[1]}]" if f[0] == "measure" else f"{f[1]}[{f[2]}]" for f in fs)
                               for role, fs in v.roles.items()) if v.roles else " / ".join(v.text[:1])
            if v.sort:
                fields += f" · sorted by {v.sort[0][-1]} {v.sort[1].lower()}"
            out.append(f"| {v.title or 'Text: ' + v.text[0]} | `{v.type}` | {v.x}, {v.y}, {v.w}, {v.h} | {fields} |")
        out.append("")
    return "\n".join(out)
