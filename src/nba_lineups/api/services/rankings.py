"""Lineup rankings: actual performance (SQL) and frozen-model predictions (the predictor's cached season frame).

Both rank ACROSS EVERY QUALIFYING LINEUP of the season (or of one team) before paging, so rank 1 on page 1 is
the league-wide best, and page 2 continues the same ordering. Ties share a rank (standard competition ranking:
1, 2, 2, 4); within a tie, larger samples are listed first, then lineup id, so the order is deterministic.

Actual rankings reuse the single SQL definition of a rating (v_lineup_window_ratings / v_lineup_season_ratings:
aggregate, then divide). Predicted rankings reuse the frozen model's per-season scores (pre-break inputs only;
for the season in progress, up to the data cutoff) and its uncertainty; nothing is refitted.
"""
from __future__ import annotations

import math

import numpy as np
import psycopg

from ...config import LIVE_SEASONS
from .. import db
from ..errors import NotFound
from .catalog import require_season, require_team
from .common import PageParams, h, page
from .lineups import players_of
from .predictions import FrozenPredictor, provisional_notes

WINDOWS = {"season": None, "pre": "pre_asb", "post": "post_asb"}
METRICS = {   # public name -> (SQL column, direction, label)
    "net": ("net_rating", "DESC", "net rating"),
    "off": ("off_rating", "DESC", "offensive rating"),
    "def": ("def_rating", "ASC", "defensive rating (lower is better)"),
    "poss": ("poss", "DESC", "possessions"),
}


def reliability(k: float | None, tau2: float | None, poss, opp_poss) -> float | None:
    """Share of a lineup's net-rating deviation from its team that is signal: τ²/(τ² + K·h) (Phase 4/5 model)."""
    hh = h(poss, opp_poss)
    if k is None or tau2 is None or not hh:
        return None
    return tau2 / (tau2 + k * hh)


SMALL_SAMPLE_POSS = 100


def reliability_tier(rel: float | None) -> str | None:
    """Plain-language reading of the signal share (None when the model's noise constants are unavailable)."""
    if rel is None:
        return None
    return "low" if rel < 0.25 else "limited" if rel < 0.5 else "moderate" if rel < 0.75 else "high"


def _window_meta(conn: psycopg.Connection, season: str, window: str) -> dict:
    wins = {r["window_type"]: r for r in db.fetch_all(
        conn, "SELECT window_type, date_from, date_to FROM stat_windows WHERE season_id = %(s)s", {"s": season})}
    live = season in LIVE_SEASONS
    if window == "season":
        if not wins:
            return {"label": "Full season", "date_from": None, "date_to": None, "available": False}
        return {"label": "Season to date" if live else "Full season", "available": True,
                "date_from": min(w["date_from"] for w in wins.values()), "date_to": max(w["date_to"] for w in wins.values())}
    w = wins.get(WINDOWS[window])
    label = "Pre-All-Star break" if window == "pre" else "Post-All-Star break"
    if live and w is not None and "post_asb" not in wins and window == "pre":
        label += " (season to date)"
    return {"label": label, "available": w is not None, "date_from": w and w["date_from"], "date_to": w and w["date_to"]}


def actual(conn: psycopg.Connection, *, season: str, team_id: int | None, window: str, metric: str,
           min_poss: int, p: PageParams, k: float | None, tau2: float | None) -> dict:
    require_season(conn, season)
    if team_id is not None:
        require_team(conn, team_id)
    col, direction, label = METRICS[metric]
    if WINDOWS[window] is None:
        source = "v_lineup_season_ratings r ON r.lineup_id = l.lineup_id"
        gp = "NULL::int"
    else:
        source = "v_lineup_window_ratings r ON r.lineup_id = l.lineup_id AND r.window_type = %(wt)s"
        gp = "r.gp"
    params = {"season": season, "team": team_id, "wt": WINDOWS[window], "min": min_poss,
              "limit": p.page_size, "offset": p.offset}
    rows = db.fetch_all(conn, f"""
        WITH q AS (
            SELECT l.lineup_id, l.season_id, l.team_id, t.abbreviation AS team_abbreviation, t.team_name,
                   {gp} AS gp, r.minutes::float8 AS minutes, r.poss, r.opp_poss,
                   r.off_rating::float8 AS off_rating, r.def_rating::float8 AS def_rating,
                   r.net_rating::float8 AS net_rating
            FROM lineups l JOIN teams t USING (team_id) JOIN {source}
            WHERE l.season_id = %(season)s AND (%(team)s::int IS NULL OR l.team_id = %(team)s)
              AND least(r.poss, coalesce(r.opp_poss, 0)) >= %(min)s
              AND r.{col} IS NOT NULL),
        ranked AS (
            SELECT q.*, rank() OVER (ORDER BY {col} {direction}) AS rank, count(*) OVER () AS total FROM q)
        SELECT * FROM ranked ORDER BY rank, poss DESC, lineup_id LIMIT %(limit)s OFFSET %(offset)s""", params)
    total = rows[0]["total"] if rows else (0 if p.offset == 0 else None)
    if total is None:
        total = db.fetch_one(conn, f"""SELECT count(*) AS n FROM lineups l JOIN {source}
            WHERE l.season_id = %(season)s AND (%(team)s::int IS NULL OR l.team_id = %(team)s)
              AND least(r.poss, coalesce(r.opp_poss, 0)) >= %(min)s AND r.{col} IS NOT NULL""", params)["n"]
    names = players_of(conn, [r["lineup_id"] for r in rows])
    items = []
    for r in rows:
        rel = reliability(k, tau2, r["poss"], r["opp_poss"])
        hh = h(r["poss"], r["opp_poss"])
        items.append({k_: r[k_] for k_ in ("rank", "lineup_id", "season_id", "team_id", "team_abbreviation", "team_name",
                                          "gp", "minutes", "poss", "opp_poss", "off_rating", "def_rating", "net_rating")}
                     | {"players": names[r["lineup_id"]], "reliability": rel,
                        "net_rating_sampling_sd": math.sqrt(k * hh) if k is not None and hh else None,
                        "reliability_tier": reliability_tier(rel),
                        "small_sample": min(r["poss"], r["opp_poss"] or 0) < SMALL_SAMPLE_POSS})
    out = page(items, total, p)
    return out | {"season_id": season, "team_id": team_id, "window": window, "metric": metric,
                  "metric_label": label, "min_poss": min_poss, "window_info": _window_meta(conn, season, window),
                  "provisional": season in LIVE_SEASONS}


def predicted(conn: psycopg.Connection, predictor: FrozenPredictor, *, season: str, team_id: int | None,
              min_pre_poss: int, possessions: int, p: PageParams) -> dict:
    require_season(conn, season)
    if team_id is not None:
        require_team(conn, team_id)
    try:
        sd = predictor.season(conn, season)
    except NotFound:
        sd = None
    if sd is None:
        f = None
    else:
        f = sd.frame
        if team_id is not None:
            f = f[f.team_id == team_id]
        f = f[np.minimum(f.lu_poss, f.lu_opp_poss) >= min_pre_poss]
        # rank on the prediction (ties share a rank); within a tie, bigger pre-break sample first, then id
        f = f.assign(_neg_poss=-f.lu_poss, _id=f.index).sort_values(["predicted", "_neg_poss", "_id"],
                                                                     ascending=[False, True, True], kind="stable")
        f = f.assign(rank=f.predicted.rank(method="min", ascending=False).astype(int))
    total = 0 if f is None else len(f)
    sl = [] if f is None else f.iloc[p.offset:p.offset + p.page_size]
    ids = [int(i) for i in (sl.index if len(sl) else [])]
    names = players_of(conn, ids)
    teams = {r["team_id"]: r for r in db.fetch_all(conn, "SELECT team_id, abbreviation, team_name FROM teams")}
    items = []
    for lid, r in (sl.iterrows() if len(sl) else []):
        pred, prior = float(r.predicted), float(r.team_prior)
        u = predictor.uncertainty(pred, possessions)
        t = teams[int(r.team_id)]
        items.append({
            "rank": int(r["rank"]), "lineup_id": int(lid), "kind": "recorded", "season_id": season,
            "team_id": int(r.team_id), "team_abbreviation": t["abbreviation"], "team_name": t["team_name"],
            "players": names[int(lid)], "predicted_net_rating": pred, "team_prior": prior,
            "model_minus_team_prior": pred - prior,
            "true_rating_interval_95": u["true_rating_interval_95"],
            "observed_rating_interval_95": u["observed_rating_interval_95"],
            "pre_break_poss": int(r.lu_poss), "pre_break_opp_poss": int(r.lu_opp_poss),
            "pre_break_net_rating": None if np.isnan(r.lu_net_raw) else float(r.lu_net_raw),
            "pre_break_reliability": float(r.lu_reliability), "no_pre_break_history": bool(r.lu_no_history == 1)})
    out = page(items, total, p)
    preds = [] if f is None else f.predicted.to_numpy()
    return out | {
        "season_id": season, "team_id": team_id, "min_pre_poss": min_pre_poss, "possessions": possessions,
        "provisional": season in LIVE_SEASONS, "data_cutoff": sd.data_cutoff if sd is not None else None,
        "season_progress": sd.progress if sd is not None else None,
        "season_used_for_training": season in predictor.trained_seasons,
        "model_sd": predictor.model_sd, "interval_half_width": 1.959963984540054 * predictor.model_sd,
        "prediction_spread": float(np.percentile(preds, 90) - np.percentile(preds, 10)) if len(preds) >= 2 else None,
        "notes": predictor_notes(predictor, season, sd.progress if sd is not None else None)}


def predictor_notes(predictor: FrozenPredictor, season: str, progress: dict | None = None) -> list[str]:
    from .model_info import ESTIMAND
    notes = [ESTIMAND, predictor.reports.team_prior_note(),
             "Ranked: recorded five-man units that played together before the break. Hypothetical combinations "
             "are not ranked (there are millions); score one on the Predict page.",
             "The model predicts how well a lineup would play IF used after the break, not how many minutes it "
             "will get.",
             "Each prediction has the same 95% interval width; neighbouring ranks are far closer together than that "
             "width, so the order is weak evidence."]
    if predictor.demo:
        from .predictions import DEMO_NOTE
        notes.insert(0, DEMO_NOTE)
    if season in LIVE_SEASONS:
        notes.append("PROVISIONAL: the season is in progress; inputs are pre-break games up to the data cutoff.")
        notes.extend(provisional_notes(progress))
    if season in predictor.trained_seasons:
        notes.append(f"In-sample: {season} was a training season.")
    return notes
