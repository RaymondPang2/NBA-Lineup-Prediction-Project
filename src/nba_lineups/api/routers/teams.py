from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from ..deps import Conn, Paging, Predictor, SeasonQ
from ..errors import NotFound
from ..schemas import ErrorResponse, Page, Prediction, TeamSeason
from ..services import teams as svc

router = APIRouter(prefix="/teams", tags=["teams"])
TeamId = Annotated[int, Path(gt=0)]
NOT_FOUND = {404: {"model": ErrorResponse, "description": "season or team not found"}}


@router.get("/stats", response_model=list[TeamSeason], responses=NOT_FOUND, summary="All teams' ratings in a season")
def all_team_stats(conn: Conn, season: SeasonQ):
    """Pre- and post-break offensive, defensive and net ratings (from lineup totals) and win-loss records."""
    return svc.team_seasons(conn, season)


@router.get("/{team_id}/stats", response_model=TeamSeason, responses=NOT_FOUND, summary="One team's ratings")
def team_stats(team_id: TeamId, conn: Conn, season: SeasonQ):
    rows = svc.team_seasons(conn, season, team_id)
    if not rows:
        raise NotFound(f"team {team_id} has no data in {season}")
    return rows[0]


@router.get("/{team_id}/predictions", response_model=Page[Prediction], responses=NOT_FOUND,
            summary="Frozen-model predictions for a team's lineups")
def team_predictions(
    team_id: TeamId, conn: Conn, predictor: Predictor, paging: Paging, season: SeasonQ,
    min_pre_poss: Annotated[int, Query(ge=0, le=5000, description="minimum pre-break possessions per end")] = 50,
    possessions: Annotated[int, Query(ge=10, le=3000)] = 100,
):
    """The team's lineups ranked by predicted post-break net rating (highest first), each with the team-prior
    baseline. Differences between lineups of the same team are small next to the uncertainty: read the
    ranking as weak evidence."""
    frame = predictor.predict_team(conn, season, team_id, min_pre_poss).sort_values(
        ["predicted"], ascending=False, kind="stable")
    ids = [int(i) for i in frame.index[paging.offset:paging.offset + paging.page_size]]
    items = [predictor.predict_lineup(conn, i, possessions, include_observed=False) for i in ids]
    return {"items": items, "page": paging.page, "page_size": paging.page_size, "total": len(frame),
            "total_pages": -(-len(frame) // paging.page_size)}
