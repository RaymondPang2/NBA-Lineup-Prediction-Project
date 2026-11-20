"""Serving the FROZEN Phase 6 model. Read-only by construction.

Startup (FrozenPredictor.__init__) refuses to serve unless:
  1. frozen_spec.json is marked frozen and the artifact's SHA-256 equals the one it records;
  2. holdout.unlock() succeeds (it re-checks 1 and, by default, that both files are committed unchanged);
  3. the loaded bundle is the model the spec names, with the same features.
The bundle is loaded once with joblib.load and only ever PREDICTS: nothing in the API package calls a
fit/refit method or writes model files (tests/api/test_model_integrity.py checks the source and the artifact).

Leakage contract: features come only from raw.load_pre_break_tables (pre_asb rows; PreBreakTables.validate
re-checks). The observed post-break result, when requested, is read by a SEPARATE query after the
prediction is made, and returned in its own field.

Per season, features and predictions for every lineup are computed once (< 1 s) and cached in memory. For the
season in progress the cache is keyed by its data version (the id of the last refresh that loaded data), so a
completed daily refresh is picked up on the next request: no restart, nothing pushed from the refresh job.
Its predictions are PROVISIONAL: season-to-date pre-break inputs, not validated at that point of a season.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from ...config import HELDOUT_SEASONS, LIVE_SEASONS
from ...refresh.freshness import data_version
from ...modeling import final, holdout, raw
from ...modeling.models import FEATURES
from .. import db
from ..errors import BadRequest, ModelUnavailable, NotFound
from .model_info import DESCRIPTIONS, ESTIMAND, ModelReports

Z95 = 1.959963984540054
CUSTOM_ID = -1            # placeholder id for a five-man combination that never played together


class ModelIntegrityError(RuntimeError):
    pass


@dataclass
class SeasonData:
    tables: raw.PreBreakTables
    frame: pd.DataFrame                    # index lineup_id: features, auxiliaries, prediction, baselines
    by_key: dict[tuple[int, tuple[int, ...]], int]   # (team_id, sorted player ids) -> lineup_id
    data_cutoff: object = None             # season in progress: last game date in its inputs


def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


class FrozenPredictor:
    def __init__(self, model_dir: Path, reports_dir: Path, require_git_freeze: bool = True):
        spec_path, artifact = model_dir / final.SPEC, model_dir / final.ARTIFACT
        self.spec = json.loads(spec_path.read_text())
        if self.spec.get("status") != "frozen":
            raise ModelIntegrityError("frozen_spec.json is not marked frozen")
        self.artifact_path, self.spec_path = artifact, spec_path
        self.artifact_sha256 = final.sha256(artifact)
        if self.artifact_sha256 != self.spec["artifact"]["sha256"]:
            raise ModelIntegrityError("model artifact does not match frozen_spec.json (SHA-256 mismatch)")
        self.spec_sha256 = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        self._key = holdout.unlock(model_dir, git_check=require_git_freeze)
        self.model = final.load(model_dir)
        m = self.spec["model"]
        if self.model.model_name != m["name"] or list(self.model.features) != m["features_in"] \
                or self.features_used != m["features_used"]:
            raise ModelIntegrityError("loaded model differs from the frozen specification")
        self.trained_seasons = tuple(self.model.trained_seasons)
        self.k = float(self.model.noise_k)
        self.reports = ModelReports.load(model_dir, reports_dir)
        self.model_sd, self.model_sd_source = self.reports.model_error_sd()
        self._parameters_fingerprint = self.parameters_fingerprint()
        self._cache: dict[tuple[str, int], SeasonData] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ integrity
    @property
    def features_used(self) -> list[str]:
        return list(self.model.pipeline[:-1].get_feature_names_out())

    def parameters_fingerprint(self) -> str:
        """Hash of every fitted number in the pipeline: changes if anything mutates the in-memory model."""
        p = self.model.pipeline
        parts = [p.named_steps["impute"].statistics_, p.named_steps["scale"].mean_, p.named_steps["scale"].scale_,
                 p.named_steps["model"].coef_, np.atleast_1d(p.named_steps["model"].intercept_)]
        return hashlib.sha256(b"".join(np.ascontiguousarray(a, dtype=float).tobytes() for a in parts)).hexdigest()

    def verify(self) -> bool:
        """Artifact on disk and model in memory both unchanged since startup."""
        return (final.sha256(self.artifact_path) == self.spec["artifact"]["sha256"]
                and self.parameters_fingerprint() == self._parameters_fingerprint)

    # ------------------------------------------------------------------ scoring
    def _score(self, tables: raw.PreBreakTables, lineups: pd.DataFrame) -> pd.DataFrame:
        frame = self.model.feature_frame(tables, lineups)
        frame["predicted"] = self.model.predict_frame(frame)
        frame = frame.join(self.model.baseline_predictions(frame))
        return frame.set_index("lineup_id")

    def season(self, conn: psycopg.Connection, season_id: str) -> SeasonData:
        version = data_version(conn, season_id) if season_id in LIVE_SEASONS else 0
        key = (season_id, version)
        if key in self._cache:
            return self._cache[key]
        with self._lock:
            if key not in self._cache:
                tables = raw.load_pre_break_tables(conn, [season_id], key=self._key)
                if tables.lineups.empty:
                    raise NotFound(f"no pre-break data for season {season_id}")
                lineups = (tables.members[["lineup_id", "season_id", "team_id"]].drop_duplicates()
                           .sort_values("lineup_id").reset_index(drop=True))
                frame = self._score(tables, lineups)
                keys = tables.members.sort_values("player_id").groupby("lineup_id").agg(
                    team_id=("team_id", "first"), players=("player_id", tuple))
                by_key = {(int(r.team_id), tuple(int(p) for p in r.players)): int(lid) for lid, r in keys.iterrows()}
                cutoff = None
                if season_id in LIVE_SEASONS:
                    cutoff = conn.execute("SELECT date_to FROM stat_windows WHERE season_id = %s AND "
                                          "window_type = 'pre_asb'", (season_id,)).fetchone()[0]
                for old in [k for k in self._cache if k[0] == season_id]:     # superseded refreshes
                    del self._cache[old]
                self._cache[key] = SeasonData(tables, frame, by_key, cutoff)
        return self._cache[key]

    def _custom_row(self, sd: SeasonData, season_id: str, team_id: int, players: list[int]) -> pd.Series:
        t = sd.tables
        extra = pd.DataFrame({"lineup_id": CUSTOM_ID, "season_id": season_id, "team_id": team_id, "player_id": players})
        members = pd.concat([t.members, extra.astype(t.members.dtypes.to_dict())], ignore_index=True)
        tables = raw.PreBreakTables(t.lineups, members, t.usage, t.player_team, t.pairs, key=t.key)
        lineup = pd.DataFrame({"lineup_id": [CUSTOM_ID], "season_id": [season_id], "team_id": [team_id]})
        return self._score(tables, lineup).loc[CUSTOM_ID]

    # ------------------------------------------------------------------ public API
    def predict_lineup(self, conn: psycopg.Connection, lineup_id: int, possessions: int,
                       include_observed: bool) -> dict:
        row = db.fetch_one(conn, "SELECT season_id, team_id FROM lineups WHERE lineup_id = %(id)s", {"id": lineup_id})
        if row is None:
            raise NotFound(f"lineup {lineup_id} not found")
        sd = self.season(conn, row["season_id"])
        r = sd.frame.loc[lineup_id]
        players = sorted(int(p) for p in sd.tables.members.loc[sd.tables.members.lineup_id == lineup_id, "player_id"])
        out = self._response(conn, sd, r, lineup_id, row["season_id"], row["team_id"], players, possessions)
        if include_observed:
            out["observed_post_break"] = observed_post_break(conn, lineup_id)
        return out

    def predict_custom(self, conn: psycopg.Connection, season_id: str, team_id: int, player_ids: list[int],
                       possessions: int, include_observed: bool = False) -> dict:
        if db.fetch_one(conn, "SELECT 1 FROM seasons WHERE season_id = %(s)s", {"s": season_id}) is None:
            raise NotFound(f"season {season_id} not found")
        if db.fetch_one(conn, "SELECT 1 FROM teams WHERE team_id = %(t)s", {"t": team_id}) is None:
            raise NotFound(f"team {team_id} not found")
        sd = self.season(conn, season_id)
        roster = set(sd.tables.members.loc[sd.tables.members.team_id == team_id, "player_id"].astype(int))
        if not roster:
            raise NotFound(f"team {team_id} has no lineups in {season_id}")
        missing = sorted(set(player_ids) - roster)
        if missing:
            raise BadRequest(f"players {missing} never appeared in a {season_id} lineup for team {team_id}",
                             details={"not_on_team": missing})
        players = sorted(player_ids)
        lineup_id = sd.by_key.get((team_id, tuple(players)))
        if lineup_id is not None:          # an existing lineup: identical to GET /lineups/{id}/prediction
            return self.predict_lineup(conn, lineup_id, possessions, include_observed)
        r = self._custom_row(sd, season_id, team_id, players)
        return self._response(conn, sd, r, None, season_id, team_id, players, possessions)

    def predict_team(self, conn: psycopg.Connection, season_id: str, team_id: int, min_pre_poss: int) -> pd.DataFrame:
        sd = self.season(conn, season_id)
        f = sd.frame[sd.frame.team_id == team_id]
        if f.empty:
            raise NotFound(f"team {team_id} has no lineups in {season_id}")
        return f[np.minimum(f.lu_poss, f.lu_opp_poss) >= min_pre_poss]

    # ------------------------------------------------------------------ response assembly
    def contributions(self, r: pd.Series) -> tuple[float, list[dict]]:
        pipe = self.model.pipeline
        z = pipe[:-1].transform(pd.DataFrame([r[FEATURES].astype(float)]))
        coef = pipe.named_steps["model"].coef_
        out = [{"feature": f, "description": DESCRIPTIONS.get(f, f), "value": _f(r[f]),
                "contribution": float(c * z[f].iloc[0])} for f, c in zip(z.columns, coef)]
        return float(pipe.named_steps["model"].intercept_), sorted(out, key=lambda d: -abs(d["contribution"]))

    def uncertainty(self, prediction: float, possessions: int) -> dict:
        sampling = math.sqrt(self.k * 2.0 / possessions)
        total = math.hypot(self.model_sd, sampling)
        return {"possessions": possessions, "model_sd": self.model_sd, "sampling_sd": sampling, "total_sd": total,
                "true_rating_interval_95": {"lo": prediction - Z95 * self.model_sd, "hi": prediction + Z95 * self.model_sd},
                "observed_rating_interval_95": {"lo": prediction - Z95 * total, "hi": prediction + Z95 * total},
                "method": (f"Normal approximation. model_sd from the {self.model_sd_source}: "
                           f"sqrt(RMSE² − noise floor²), possession-weighted, one value for every lineup. "
                           f"sampling_sd = sqrt(K·(1/poss + 1/opp_poss)) with K = {self.k:.0f} fitted on the "
                           f"development seasons and poss = opp_poss = {possessions}.")}

    def _players(self, conn, sd: SeasonData, team_id: int, players: list[int]) -> list[dict]:
        names = {r["player_id"]: r["player_name"] for r in db.fetch_all(
            conn, "SELECT player_id, player_name FROM players WHERE player_id = ANY(%(p)s)", {"p": players})}
        pt = sd.tables.player_team
        pt = pt[pt.player_id.isin(players)]
        any_team = pt.groupby("player_id").on_poss.sum()
        this_team = pt[pt.team_id == team_id].set_index("player_id").on_poss
        return [{"player_id": p, "player_name": names.get(p, str(p)),
                 "has_pre_break_data": bool(any_team.get(p, 0) > 0),
                 "new_to_team": bool(this_team.get(p, 0) == 0)} for p in players]

    def _response(self, conn, sd: SeasonData, r: pd.Series, lineup_id: int | None, season_id: str, team_id: int,
                  players: list[int], possessions: int) -> dict:
        pred = float(r["predicted"])
        intercept, contrib = self.contributions(r)
        abbr = db.fetch_one(conn, "SELECT abbreviation FROM teams WHERE team_id = %(t)s", {"t": team_id})["abbreviation"]
        plist = self._players(conn, sd, team_id, players)
        in_sample = season_id in self.trained_seasons
        notes = [ESTIMAND, f"Inputs: pre-All-Star-break data of {season_id} only.", self.reports.team_prior_note()]
        if in_sample:
            notes.append(f"In-sample: {season_id} is a training season, so lineups with ≥ 25 post-break possessions "
                         "per end were training labels. Use the held-out seasons "
                         f"({', '.join(HELDOUT_SEASONS)}) to judge accuracy.")
        provisional = season_id in LIVE_SEASONS
        if provisional:
            notes.append(
                f"PROVISIONAL: {season_id} is in progress. The inputs are its pre-All-Star-break games played so far "
                f"(through {sd.data_cutoff}); nothing after that date is used and nothing is extrapolated.")
            notes.append(
                "The frozen model was developed and evaluated on COMPLETED pre-break windows (about 55 games per team). "
                "Applied to a partial window it has not been independently validated: early-season inputs are far "
                "noisier, so the prediction and its 95% intervals (calibrated on completed windows) are optimistic. "
                "The team-prior baseline is computed from the same season-to-date data.")
        if r["lu_no_history"] == 1:
            notes.append("No pre-break minutes together: the prediction relies on team and player information only; "
                         "for such lineups the model adds nothing measurable over the team prior.")
        if any(not p["has_pre_break_data"] for p in plist):
            notes.append("At least one player has no pre-break data this season and gets a fringe-player prior: "
                         "biased low if that player is a returning regular.")
        return {
            "lineup_id": lineup_id, "season_id": season_id, "team_id": int(team_id), "team_abbreviation": abbr,
            "players": plist, "predicted_net_rating": pred,
            "baselines": {"team_prior": float(r["team_prior"]), "league_mean": float(r["league_mean"]),
                          "eb_lineup_team": float(r["eb_lineup_team"])},
            "model_minus_team_prior": pred - float(r["team_prior"]),
            "uncertainty": self.uncertainty(pred, possessions),
            "pre_break": {"poss": int(r["lu_poss"]), "opp_poss": int(r["lu_opp_poss"]), "net_rating": _f(r["lu_net_raw"]),
                          "reliability": float(r["lu_reliability"]),
                          "team_net_rating_excluding_lineup": _f(r["team_net_loo"])},
            "intercept": intercept, "contributions": contrib,
            "season_used_for_training": in_sample, "provisional": provisional,
            "data_cutoff": sd.data_cutoff if provisional else None, "notes": notes}


def observed_post_break(conn: psycopg.Connection, lineup_id: int) -> dict | None:
    """The realized post-break result: read AFTER the prediction, never passed to the model."""
    r = db.fetch_one(conn, """
        SELECT poss, opp_poss, net_rating::float8 AS net_rating
        FROM v_lineup_window_ratings WHERE lineup_id = %(id)s AND window_type = 'post_asb'""", {"id": lineup_id})
    if r is None:
        return None
    r["in_evaluation_sample"] = bool(r["poss"] >= raw.MIN_TARGET_POSS and (r["opp_poss"] or 0) >= raw.MIN_TARGET_POSS)
    return r


def require(predictor: FrozenPredictor | None) -> FrozenPredictor:
    if predictor is None:
        raise ModelUnavailable("the frozen model is not loaded (see server log)")
    return predictor
