from __future__ import annotations

from fastapi import APIRouter

from ..deps import Conn, Predictor
from ..schemas import ErrorResponse, Prediction, PredictionRequest

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.post("", response_model=Prediction, summary="Predict any five players of one team",
             responses={400: {"model": ErrorResponse, "description": "a player never played for the team that season"},
                        404: {"model": ErrorResponse, "description": "season or team not found"}})
def predict(body: PredictionRequest, conn: Conn, predictor: Predictor):
    """Predict a lineup given by its five players, including combinations that never played together.

    POST because the input is a JSON body, not because anything is created or stored: the call is read-only
    and repeatable (same input → same output). If the five already form a recorded lineup, the result equals
    GET /lineups/{lineup_id}/prediction."""
    return predictor.predict_custom(conn, body.season_id, body.team_id, body.player_ids, body.possessions)
