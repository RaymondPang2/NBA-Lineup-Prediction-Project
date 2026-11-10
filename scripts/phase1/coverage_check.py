"""Phase 1 coverage check: is there enough data for modelling? (offline; reads data/raw only)

For each ingested season, counts post-All-Star-break lineups (the conditional
target sample) at several possession thresholds, and how many of them have
pre-break data for all 5 players (needed for the primary player-level features).

It then compares the counts against a sample-size gate derived from a power
calculation (Fisher z-transform for a correlation).

Usage:  .venv/bin/python scripts/phase1/coverage_check.py
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import NormalDist

import pandas as pd

RAW = Path("data/raw")
THRESHOLDS = (1, 25, 50, 100)


def load_lineups(season: str, window: str) -> pd.DataFrame:
    frames = []
    for path in sorted((RAW / season / "leaguedashlineups" / window / "advanced").glob("team_*.json")):
        rs = json.loads(path.read_text())["resultSets"][0]
        frames.append(pd.DataFrame(rs["rowSet"], columns=rs["headers"]))
    return pd.concat(frames, ignore_index=True)


def n_for_correlation(r: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Sample size to detect correlation r (two-sided): n = ((z_{1-a/2} + z_{power}) / atanh(r))^2 + 3."""
    z = NormalDist().inv_cdf
    return math.ceil(((z(1 - alpha / 2) + z(power)) / math.atanh(r)) ** 2 + 3)


def main() -> None:
    # only real season folders (e.g. "2023-24"); data/raw/phase0/ holds the old spike cache
    seasons = sorted(p.name for p in RAW.iterdir() if re.fullmatch(r"\d{4}-\d{2}", p.name) and (p / "windows.json").exists())
    rows = []
    for season in seasons:
        pre, post = load_lineups(season, "pre_asb"), load_lineups(season, "post_asb")
        pre["PLAYERS"] = pre.GROUP_ID.str.strip("-").str.split("-")
        players_pre = {(t, p) for t, ps in zip(pre.TEAM_ID, pre.PLAYERS) for p in ps}
        post["ALL5_PRE"] = [all((t, p) in players_pre for p in g.strip("-").split("-"))
                            for t, g in zip(post.TEAM_ID, post.GROUP_ID)]
        for th in THRESHOLDS:
            s = post[post.POSS >= th]
            rows.append({"season": season, "min_post_poss": th, "lineups": len(s),
                         "all5_have_pre_data": int(s.ALL5_PRE.sum()), "post_poss_covered": int(s.POSS.sum()),
                         "share_of_post_poss": round(s.POSS.sum() / post.POSS.sum(), 3)})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 140)
    print(df.to_string(index=False))

    print("\nPower calculation (alpha=0.05 two-sided, power=0.80):")
    for r in (0.15, 0.20, 0.25):
        print(f"  to detect r = {r:.2f} need n >= {n_for_correlation(r)}")

    print("\nPer-season mean (measured seasons only) of lineups with all 5 players' pre-break data:")
    print(df.groupby("min_post_poss").all5_have_pre_data.mean().round(0).to_string())


if __name__ == "__main__":
    main()
