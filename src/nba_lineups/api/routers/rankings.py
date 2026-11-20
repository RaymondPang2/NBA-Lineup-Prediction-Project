from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from ..deps import K, Conn, Paging, Predictor, SeasonQ
from ..schemas import ErrorResponse, LineupRanking, PredictionRanking
from ..services import rankings as svc

router = APIRouter(prefix="/rankings", tags=["rankings"])
NOT_FOUND = {404: {"model": ErrorResponse, "description": "season or team not found"}}
TeamQ = Annotated[int | None, Query(gt=0, description="one team; omit for league-wide")]


@router.get("/lineups", response_model=LineupRanking, responses=NOT_FOUND, summary="Lineups ranked by actual results")
def rank_lineups(
    request: Request, conn: Conn, k: K, paging: Paging, season: SeasonQ, team_id: TeamQ = None,
    window: Annotated[Literal["season", "pre", "post"], Query(description="season = full season (season to date "
                                                                         "for the season in progress)")] = "season",
    metric: Literal["net", "off", "def", "poss"] = "net",
    min_poss: Annotated[int, Query(ge=0, le=5000, description="minimum possessions on EACH end in the window")] = 100,
):
    """Every qualifying lineup of the season (or team) is ranked before paging, so ranks are global.
    `def` ranks the LOWEST defensive rating first; `poss` ranks by own possessions (most used).
    Each row carries a sampling SD and a reliability (signal share) so small samples are visible."""
    p = request.app.state.predictor
    tau2 = float(p.model.builder.lineup_vc_.tau2) if p is not None else None
    return svc.actual(conn, season=season, team_id=team_id, window=window, metric=metric, min_poss=min_poss,
                      p=paging, k=k, tau2=tau2)


@router.get("/predictions", response_model=PredictionRanking, responses=NOT_FOUND,
            summary="Recorded lineups ranked by the frozen model's prediction")
def rank_predictions(
    conn: Conn, predictor: Predictor, paging: Paging, season: SeasonQ, team_id: TeamQ = None,
    min_pre_poss: Annotated[int, Query(ge=0, le=5000, description="minimum pre-break possessions per end")] = 50,
    possessions: Annotated[int, Query(ge=10, le=3000)] = 100,
):
    """Recorded lineups ranked by predicted post-All-Star-break net rating (pre-break inputs only; for the season
    in progress, up to the data cutoff), each with the team-prior baseline and 95% intervals. The model is NOT
    shown to beat the team-prior baseline, and neighbouring ranks differ by far less than the interval width:
    read the order as weak evidence. It predicts quality if played, not playing time."""
    return svc.predicted(conn, predictor, season=season, team_id=team_id, min_pre_poss=min_pre_poss,
                         possessions=possessions, p=paging)
