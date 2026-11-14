from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ..deps import K, Conn, OptSeasonQ, Order, Paging, Predictor
from ..errors import BadRequest
from ..schemas import ErrorResponse, LineupDetail, LineupSummary, Page, Prediction
from ..services import lineups as svc

router = APIRouter(prefix="/lineups", tags=["lineups"])
NOT_FOUND = {404: {"model": ErrorResponse, "description": "lineup not found"}}
LineupId = Annotated[int, Path(gt=0, description="lineup id (from GET /lineups)")]


@router.get("", response_model=Page[LineupSummary], summary="Five-man lineups, pre vs post break")
def list_lineups(
    conn: Conn, k: K, paging: Paging,
    season: OptSeasonQ = None,
    team_id: Annotated[int | None, Query(gt=0)] = None,
    player_id: Annotated[list[int], Query(description="lineups containing ALL of these players (repeat the "
                                                      "parameter, up to 5)")] = [],
    min_pre_poss: Annotated[int, Query(ge=0, le=5000, description="minimum pre-break possessions on EACH end")] = 0,
    min_post_poss: Annotated[int, Query(ge=0, le=5000, description="minimum post-break possessions on EACH end")] = 0,
    sort: Literal[tuple(svc.SORTS)] = "pre_poss",
    order: Order = "desc",
):
    """Filter by season, team, player(s) and minimum possessions. Each lineup carries its pre-break and
    post-break ratings, the change, and how large a change sampling noise alone would produce.

    Possession thresholds apply to BOTH ends (own and opponent possessions), as in the model's target sample
    (≥ 25 post-break possessions per end)."""
    if len(player_id) > 5 or len(set(player_id)) != len(player_id) or any(p <= 0 for p in player_id):
        raise BadRequest("player_id: up to five distinct positive ids")
    if season is None and team_id is None and not player_id:
        raise BadRequest("give at least one of season, team_id or player_id (all lineups of all seasons is "
                         "~130,000 rows)")
    return svc.list_lineups(conn, season=season, team_id=team_id, player_ids=player_id, min_pre_poss=min_pre_poss,
                            min_post_poss=min_post_poss, sort=sort, order=order, p=paging, k=k)


@router.get("/{lineup_id}", response_model=LineupDetail, responses=NOT_FOUND, summary="One lineup")
def get_lineup(lineup_id: LineupId, conn: Conn, k: K):
    return svc.get_lineup(conn, lineup_id, k)


@router.get("/{lineup_id}/prediction", response_model=Prediction, responses=NOT_FOUND,
            summary="Frozen-model prediction for a lineup")
def predict_lineup(
    lineup_id: LineupId, conn: Conn, predictor: Predictor,
    possessions: Annotated[int, Query(ge=10, le=3000, description="post-break possessions per end to size the "
                                                                  "observed-rating interval for")] = 100,
    include_observed: Annotated[bool, Query(description="also return what actually happened after the break "
                                                        "(read separately; never a model input)")] = False,
):
    """Post-break net rating predicted from PRE-BREAK data only, conditional on the lineup playing after the
    break, with the team-prior baseline, uncertainty and per-feature contributions."""
    return predictor.predict_lineup(conn, lineup_id, possessions, include_observed)
