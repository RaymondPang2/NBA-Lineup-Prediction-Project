from __future__ import annotations

from fastapi import APIRouter

from ..deps import Conn, OptSeasonQ
from ..schemas import Season, Team
from ..services import catalog

router = APIRouter(tags=["catalog"])


@router.get("/seasons", response_model=list[Season], summary="Seasons in the database")
def list_seasons(conn: Conn):
    """Every loaded season with its pre/post All-Star-break windows, whether it is irregular, and its role:
    `development` (used to train the frozen model) or `held_out` (its final test seasons)."""
    return catalog.seasons(conn)


@router.get("/teams", response_model=list[Team], summary="Teams")
def list_teams(conn: Conn, season: OptSeasonQ = None):
    """All franchises, or only those with lineups in `season`."""
    return catalog.teams(conn, season)
