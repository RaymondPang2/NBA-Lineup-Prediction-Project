from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ..deps import Conn, OptSeasonQ, Order, Paging, SeasonQ
from ..schemas import ErrorResponse, Page, PlayerDetail, PlayerTeamSeason
from ..services import catalog
from ..services import players as svc

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=Page[PlayerTeamSeason], summary="Player on-court and on/off stats")
def list_players(
    conn: Conn, paging: Paging, season: SeasonQ,
    team_id: Annotated[int | None, Query(gt=0)] = None,
    search: Annotated[str | None, Query(min_length=2, max_length=50, description="case-insensitive name search")] = None,
    min_pre_minutes: Annotated[float, Query(ge=0, le=5000)] = 0,
    sort: Literal[tuple(svc.SORTS)] = "pre_minutes",
    order: Order = "desc",
):
    """One row per player and team in `season` (a traded player has one row per team). On-court ratings and
    on/off come from lineup data; usage from the player endpoint (all teams combined)."""
    catalog.require_season(conn, season)
    if team_id is not None:
        catalog.require_team(conn, team_id)
    return svc.list_players(conn, season=season, team_id=team_id, search=search, min_pre_minutes=min_pre_minutes,
                            sort=sort, order=order, p=paging)


@router.get("/{player_id}", response_model=PlayerDetail,
            responses={404: {"model": ErrorResponse, "description": "player not found"}}, summary="One player")
def get_player(conn: Conn, player_id: Annotated[int, Path(gt=0)], season: OptSeasonQ = None):
    """Every (season, team) of the player, or only `season`."""
    if season is not None:
        catalog.require_season(conn, season)
    return svc.get_player(conn, player_id, season)
