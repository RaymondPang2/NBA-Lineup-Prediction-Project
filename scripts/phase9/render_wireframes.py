"""Draw a layout WIREFRAME of each report page from the report specification (src/nba_lineups/bi/report.py).

    .venv/bin/python scripts/phase9/render_wireframes.py      # -> reports/phase9/wireframes/*.png

These are NOT Power BI screenshots and contain no data: boxes show where each visual sits, its type and its
fields, so the layout can be reviewed before the report is opened in Power BI. Every image says so.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from nba_lineups.bi import report as rp
from nba_lineups.config import PROJECT_ROOT

OUT = PROJECT_ROOT / "reports" / "phase9" / "wireframes"
FILL = {"slicer": "#e5effc", "card": "#f3f3f0", "textbox": "#ffffff", "tableEx": "#fbfbf9"}
ICON = {"clusteredBarChart": "bar chart", "clusteredColumnChart": "column chart", "lineChart": "line chart",
        "scatterChart": "scatter", "tableEx": "table", "card": "card", "slicer": "slicer", "textbox": "text"}


def _fields(v: rp.Visual) -> str:
    parts = []
    for role, fs in v.roles.items():
        names = ", ".join(f[1] if f[0] == "measure" else f[2] for f in fs)
        parts.append(names if v.type in ("card", "slicer") else f"{role}: {names}")
    return "\n".join(parts)


def render(page: rp.Page) -> None:
    fig, ax = plt.subplots(figsize=(12.8, 7.2), dpi=110)
    ax.set_xlim(0, 1280)
    ax.set_ylim(720, 0)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), 1280, 720, color="#f6f6f3", zorder=0))
    for v in page.visuals:
        ax.add_patch(FancyBboxPatch((v.x, v.y), v.w, v.h, boxstyle="round,pad=0,rounding_size=6",
                                    fc=FILL.get(v.type, "#ffffff"), ec="#c3c2b7", lw=1, zorder=1))
        if v.type == "textbox":
            ax.text(v.x + 8, v.y + 22, v.text[0], fontsize=13, weight="bold", color="#0b0b0b", va="center", zorder=2)
            body = "\n".join(v.text[1:])
            ax.text(v.x + 8, v.y + 40, body, fontsize=7, color="#52514e", va="top", wrap=True, zorder=2)
            continue
        ax.text(v.x + 8, v.y + 14, v.title or "", fontsize=8, weight="bold", color="#0b0b0b", va="center", zorder=2)
        ax.text(v.x + v.w - 8, v.y + 14, ICON.get(v.type, v.type), fontsize=6.5, color="#2a78d6", ha="right", va="center", zorder=2)
        ax.text(v.x + 8, v.y + 30, _fields(v), fontsize=6.5, color="#52514e", va="top", zorder=2, linespacing=1.3)
    ax.text(1272, 712, "LAYOUT WIREFRAME generated from the report spec · not a Power BI screenshot · no data",
            fontsize=7, color="#b42626", ha="right", va="bottom", zorder=3)
    fig.subplots_adjust(0, 0, 1, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{page.name}.png")
    plt.close(fig)


def main() -> None:
    for p in rp.PAGES:
        render(p)
    print(f"wrote {len(rp.PAGES)} wireframes to {OUT.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
