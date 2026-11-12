"""SYNTHETIC pre-break tables and targets for offline tests. The numbers are not real NBA data.

Structure mirrors raw.load_pre_break_tables: three development seasons, a few teams, lineups drawn from
each team's roster, one traded player (two teams in one season), and post-break-only lineups without
history, including one with a player who has no pre-break data at all.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from nba_lineups.modeling import raw

SEASONS = ("2018-19", "2019-20", "2020-21")
TEAMS = (1610612737, 1610612738, 1610612739)


def make(seasons=SEASONS, n_lineups: int = 40, seed: int = 0) -> tuple[raw.PreBreakTables, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    lineups, members, usage, targets = [], [], [], []
    lid = 1
    for si, season in enumerate(seasons):
        rosters = {t: [10_000 * (ti + 1) + 100 * si + j for j in range(9)] for ti, t in enumerate(TEAMS)}
        rosters[TEAMS[1]].append(rosters[TEAMS[0]][0])          # a traded player: plays for two teams
        newcomer = 999_000 + si                                  # never plays before the break
        for team, roster in rosters.items():
            combos = list(itertools.combinations(roster, 5))
            picks = rng.choice(len(combos), n_lineups + 6, replace=False)
            for k, idx in enumerate(picks):
                five = list(combos[idx])
                pre = k < n_lineups                              # the last 6 exist only after the break
                if k == n_lineups:
                    five[0] = newcomer
                if pre:
                    poss = int(rng.lognormal(3.2, 1.2))
                    opp = max(0, poss + int(rng.integers(-2, 3)))
                    q = rng.normal(0, 0.06)
                    lineups.append({"season_id": season, "team_id": team, "lineup_id": lid, "window_type": "pre_asb",
                                    "gp": 1 + poss // 20, "poss": poss, "opp_poss": opp,
                                    "pts": int(rng.poisson(max(poss, 0) * (1.1 + q))),
                                    "opp_pts": int(rng.poisson(max(opp, 0) * (1.1 - q)))})
                members += [{"lineup_id": lid, "season_id": season, "team_id": team, "player_id": p} for p in five]
                if k % 3 == 0 or not pre:
                    pp = int(rng.integers(25, 300))
                    targets.append({"season_id": season, "team_id": team, "lineup_id": lid, "post_poss": pp,
                                    "post_opp_poss": pp + int(rng.integers(-3, 4)), "y": float(rng.normal(2, 20))})
                lid += 1
    lineups = pd.DataFrame(lineups)
    members = pd.DataFrame(members)
    on = (lineups.merge(members[["lineup_id", "player_id"]], on="lineup_id")
          .groupby(["season_id", "player_id"]).poss.sum())
    usage = pd.DataFrame({"season_id": on.index.get_level_values(0), "player_id": on.index.get_level_values(1),
                          "window_type": "pre_asb", "usage_poss": (on.values * 0.97).astype(int),
                          "usg_pct": rng.uniform(0.12, 0.30, len(on))})
    t = pd.DataFrame(targets)
    t["w"] = t.post_poss.astype(float)
    t["is_irregular"] = t.season_id.isin({"2019-20", "2020-21"})
    return raw.build_tables(lineups, members, usage), t
