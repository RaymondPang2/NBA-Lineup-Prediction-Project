"""Shared Matplotlib style for report figures (static PNGs).

Palette: a validated categorical order (blue, orange, aqua) whose first three slots stay
distinguishable under common colour-vision deficiencies; every multi-series figure also has a
legend or direct labels, so identity never relies on colour alone. Text uses ink colours, never
series colours. Grid and axes are recessive.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")   # file output only; no display needed
import matplotlib.pyplot as plt  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SERIES = (BLUE, ORANGE, AQUA)
INK, INK_2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"


def apply_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.labelsize": 10, "axes.labelcolor": INK_2, "text.color": INK,
        "axes.edgecolor": MUTED, "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
        "xtick.color": INK_2, "ytick.color": INK_2, "xtick.labelsize": 9, "ytick.labelsize": 9,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "legend.frameon": False, "legend.fontsize": 9, "lines.linewidth": 2.0,
        "axes.prop_cycle": matplotlib.cycler(color=list(SERIES)),
        "figure.constrained_layout.use": True,   # panels never overlap each other's tick labels
        "figure.dpi": 100, "savefig.dpi": 160, "savefig.bbox": "tight",
    })


def save(fig, path: Path, source: str = "Source: NBA.com/stats via nba_api. Development seasons 2018-19 to 2023-24.") -> Path:
    fig.text(0.0, -0.02, source, fontsize=8, color=MUTED, ha="left", va="top", transform=fig.transFigure)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
