from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from ...refresh import freshness
from ..deps import Conn, OptSeasonQ
from ..schemas import DataStatus, Season, Team
from ..services import catalog

router = APIRouter(tags=["catalog"])


@router.get("/seasons", response_model=list[Season], summary="Seasons in the database")
def list_seasons(conn: Conn):
    """Every loaded season with its pre/post All-Star-break windows, whether it is irregular, and its role:
    `development` (used to train the frozen model), `held_out` (its final test seasons) or `current` (the season
    in progress, season to date, refreshed daily on the local machine)."""
    return catalog.seasons(conn)


@router.get("/teams", response_model=list[Team], summary="Teams")
def list_teams(conn: Conn, season: OptSeasonQ = None):
    """All franchises, or only those with lineups in `season`."""
    return catalog.teams(conn, season)


@router.get("/data-status", response_model=DataStatus, summary="Freshness of the season in progress")
def data_status(conn: Conn):
    """When the season in progress was last refreshed, the data cutoff, and whether the data is current or
    stale. Read-only: refreshes run only from the local scheduler or the terminal (`refresh_command`), never
    from the API. `data_version` changes whenever a refresh loads new data, so clients know to refetch."""
    return freshness.status(conn, datetime.now(UTC))
