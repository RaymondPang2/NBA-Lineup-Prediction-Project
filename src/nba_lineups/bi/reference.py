"""Reference implementations of the semantic model's measures, in pandas, over the exported tables.

Power BI's DAX engine does not run on macOS, so the measures are validated by re-implementing each one here,
with the SAME filter propagation as the model's relationships:

    season/team/window filters  → applied to the facts directly
    player filter               → bridge → set of lineup_ids → facts (each lineup counted once)
    'all' player semantics      → lineups containing every selected player (the AND measure)

These functions mirror the DAX in model.py line by line; tests/powerbi reconcile them against PostgreSQL views,
the Phase 6 held-out report and the Phase 4 selection findings. They are a validation tool, not the product.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import model as bim

Z = 1.959964


def load(csv_dir: Path) -> dict[str, pd.DataFrame]:
    return {t.name: pd.read_csv(csv_dir / f"{t.name}.csv") for t in bim.data_tables()}


@dataclass
class Filter:
    """A Power BI filter context: slicer selections (None = no filter)."""
    seasons: list[str] | None = None
    teams: list[int] | None = None
    window: str | None = None                 # 'pre_asb' | 'post_asb'
    players: list[int] | None = None
    players_mode: str = "any"                 # any = relationship semantics; all = AND measure as visual filter
    lineups: list[int] | None = None          # e.g. a table visual row
    lineup_attrs: dict = field(default_factory=dict)   # dim_lineup column -> value


class Model:
    def __init__(self, data: dict[str, pd.DataFrame]):
        self.d = data
        self.params = data["model_parameters"].iloc[0]

    # ------------------------------------------------------------------ filter propagation
    def lineup_set(self, f: Filter) -> set[int] | None:
        """Lineups allowed by filters on dim_lineup (players via the bridge, attributes, explicit rows)."""
        allowed: set[int] | None = None

        def meet(s: set[int]):
            nonlocal allowed
            allowed = s if allowed is None else allowed & s

        if f.players:
            b = self.d["bridge_lineup_player"]
            hit = b[b.player_id.isin(f.players)]
            if f.players_mode == "all":
                n = hit.groupby("lineup_id").player_id.nunique()
                meet(set(n[n == len(set(f.players))].index))
            else:
                meet(set(hit.lineup_id))
        if f.lineup_attrs:
            dl = self.d["dim_lineup"]
            m = np.ones(len(dl), bool)
            for k, v in f.lineup_attrs.items():
                m &= (dl[k] == v).to_numpy()
            meet(set(dl.lineup_id[m]))
        if f.lineups is not None:
            meet(set(f.lineups))
        return allowed

    def _fact(self, name: str, f: Filter, window_override: str | None = None) -> pd.DataFrame:
        x = self.d[name]
        if f.seasons is not None:
            x = x[x.season_id.isin(f.seasons)]
        if f.teams is not None:
            x = x[x.team_id.isin(f.teams)]
        w = window_override or f.window
        if w is not None and "window_type" in x:
            x = x[x.window_type == w]
        ls = self.lineup_set(f)
        if ls is not None and "lineup_id" in x:
            x = x[x.lineup_id.isin(ls)]
        return x

    def flw(self, f: Filter, window: str | None = None) -> pd.DataFrame:
        return self._fact("fact_lineup_window", f, window)

    # ------------------------------------------------------------------ ratings (aggregate, then divide)
    @staticmethod
    def _ortg(x) -> float | None:
        return 100 * x.pts.sum() / x.poss.sum() if x.poss.sum() > 0 else None

    @staticmethod
    def _drtg(x) -> float | None:
        return 100 * x.opp_pts_rated.sum() / x.opp_poss.sum() if x.opp_poss.sum() > 0 else None

    def ortg(self, f: Filter, window=None):
        return self._ortg(self.flw(f, window))

    def drtg(self, f: Filter, window=None):
        return self._drtg(self.flw(f, window))

    def net(self, f: Filter, window=None):
        o, d = self.ortg(f, window), self.drtg(f, window)
        return None if o is None or d is None else o - d

    def net_change(self, f: Filter):
        a, b = self.net(f, "pre_asb"), self.net(f, "post_asb")
        return None if a is None or b is None else b - a

    def possessions(self, f: Filter, window=None) -> int:
        return int(self.flw(f, window).poss.sum())

    def lineups(self, f: Filter) -> int:
        return int(self.flw(f).lineup_id.nunique())

    def per_lineup(self, f: Filter, window=None) -> pd.DataFrame:
        x = self.flw(f, window).groupby("lineup_id")[["pts", "poss", "opp_pts_rated", "opp_poss"]].sum()
        x["net"] = np.where((x.poss > 0) & (x.opp_poss > 0),
                            100 * x.pts / x.poss.where(x.poss > 0) - 100 * x.opp_pts_rated / x.opp_poss.where(x.opp_poss > 0), np.nan)
        return x

    def lineup_net_avg_weighted(self, f: Filter, window=None):
        x = self.per_lineup(f, window).dropna(subset=["net"])
        return float(np.average(x.net, weights=x.poss)) if x.poss.sum() > 0 else None

    def lineup_net_avg_unweighted(self, f: Filter, window=None):
        x = self.per_lineup(f, window).dropna(subset=["net"])
        return float(x.net.mean()) if len(x) else None

    # ------------------------------------------------------------------ uncertainty
    def net_se(self, f: Filter, window=None):
        x = self.flw(f, window)
        p, q = x.poss.sum(), x.opp_poss.sum()
        return float(np.sqrt(self.params.k_noise * (1 / p + 1 / q))) if p > 0 and q > 0 else None

    def reliability(self, f: Filter, window=None):
        x = self.flw(f, window)
        p, q = x.poss.sum(), x.opp_poss.sum()
        t2 = self.params.lineup_tau2
        return float(t2 / (t2 + self.params.k_noise * (1 / p + 1 / q))) if p > 0 and q > 0 else None

    def change_exceeds_noise(self, f: Filter):
        c, a, b = self.net_change(f), self.net_se(f, "pre_asb"), self.net_se(f, "post_asb")
        return None if c is None or a is None or b is None else int(abs(c) > Z * np.hypot(a, b))

    # ------------------------------------------------------------------ team
    def record(self, f: Filter) -> tuple[int, int, int]:
        x = self._fact("fact_team_window", Filter(seasons=f.seasons, teams=f.teams, window=f.window))
        return int(x.games.sum()), int(x.wins.sum()), int(x.losses.sum())

    # ------------------------------------------------------------------ model performance
    def eval_sample(self, f: Filter) -> pd.DataFrame:
        x = self._fact("fact_prediction", f)
        return x[(x.in_evaluation_sample == 1) & x.observed_post_net.notna()]

    def model_metrics(self, f: Filter) -> dict[str, float]:
        x = self.eval_sample(f)
        w, y = x.post_poss.to_numpy(float), x.observed_post_net.to_numpy(float)

        def mse(col):
            return float(np.average((y - x[col]) ** 2, weights=w))

        def mae(col):
            return float(np.average(np.abs(y - x[col]), weights=w))

        var_y = float(np.average((y - np.average(y, weights=w)) ** 2, weights=w))
        floor = float(np.average(x.noise_var, weights=w))
        return {"n": len(x), "weight": float(w.sum()),
                "model_rmse": np.sqrt(mse("predicted_net")), "team_prior_rmse": np.sqrt(mse("team_prior_net")),
                "league_mean_rmse": np.sqrt(mse("league_mean_net")),
                "model_mae": mae("predicted_net"), "team_prior_mae": mae("team_prior_net"), "league_mean_mae": mae("league_mean_net"),
                "skill_vs_team_prior": 1 - mse("predicted_net") / mse("team_prior_net"),
                "model_r2": 1 - mse("predicted_net") / var_y, "noise_floor_rmse": np.sqrt(floor), "r2_ceiling": 1 - floor / var_y,
                "mean_predicted": float(np.average(x.predicted_net, weights=w)), "mean_observed": float(np.average(y, weights=w))}

    # ------------------------------------------------------------------ selection
    def selection(self, f: Filter) -> dict[str, float]:
        x = self.flw(Filter(seasons=f.seasons, teams=f.teams, players=f.players, players_mode=f.players_mode,
                            lineups=f.lineups, lineup_attrs=f.lineup_attrs), "pre_asb")
        dl = self.d["dim_lineup"].set_index("lineup_id")
        ids = dl.loc[x.lineup_id.unique()]
        pop = ids[ids.in_continuation_population == 1]
        n = len(pop)
        return {"population": n, "continuing": int(pop.continues_post_break.sum()), "appearing": int(pop.appears_post_break.sum()),
                "continuation_rate": pop.continues_post_break.sum() / n if n else None,
                "appearance_rate": pop.appears_post_break.sum() / n if n else None}
