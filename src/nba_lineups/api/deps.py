"""FastAPI dependencies: small functions that routers declare as parameters (dependency injection).

FastAPI calls them per request and passes the result in; tests swap them out with app.dependency_overrides
(e.g. a database that always fails), without touching router code.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import Depends, Query, Request

from . import db
from .schemas import SEASON_PATTERN
from .services.common import PageParams
from .services.predictions import FrozenPredictor, require


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    yield from db.connection(request.app.state.pool)


def get_predictor(request: Request) -> FrozenPredictor:
    return require(request.app.state.predictor)


def noise_k(request: Request) -> float | None:
    """Lineup sampling-noise constant K from the frozen FeatureBuilder (None if the model isn't loaded)."""
    p = request.app.state.predictor
    return p.k if p is not None else None


def pagination(page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
               page_size: Annotated[int, Query(ge=1, le=200, description="rows per page (max 200)")] = 50) -> PageParams:
    return PageParams(page, page_size)


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
Predictor = Annotated[FrozenPredictor, Depends(get_predictor)]
K = Annotated[float | None, Depends(noise_k)]
Paging = Annotated[PageParams, Depends(pagination)]
SeasonQ = Annotated[str, Query(pattern=SEASON_PATTERN, description="season id, e.g. 2025-26", examples=["2025-26"])]
OptSeasonQ = Annotated[str | None, Query(pattern=SEASON_PATTERN, description="season id, e.g. 2025-26")]
Order = Annotated[str, Query(pattern="^(asc|desc)$")]
