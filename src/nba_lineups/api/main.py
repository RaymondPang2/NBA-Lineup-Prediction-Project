"""Application factory.

    .venv/bin/uvicorn nba_lineups.api.main:app --reload        # http://127.0.0.1:8000/docs

Startup (lifespan): open the read-only connection pool in the background and load + verify the frozen model.
If either fails, the app still starts: /health reports what is wrong and the endpoints that need the
missing part answer 503, instead of the process crash-looping.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import errors
from .db import make_pool
from .routers import catalog, health, lineups, model, players, predictions, teams
from .services.predictions import FrozenPredictor
from .settings import Settings

log = logging.getLogger("nba_lineups.api")
API_PREFIX = "/api/v1"

DESCRIPTION = """
Read-only API over eight NBA regular seasons (2018-19 to 2025-26) of five-man lineup data, split at the
All-Star break, and the **frozen** Phase 6 model that predicts a lineup's post-break net rating.

**Read before using predictions**
* A prediction is **conditional**: the expected post-break net rating *if* the lineup plays after the break.
* It uses **pre-break data only**.
* It is **not statistically better than the team-prior baseline**, which is returned with every prediction
  (see `GET /api/v1/model/performance`).
* Uncertainty is large and has two parts: the model's error about the lineup's true quality, and the sampling
  noise of a rating measured over a few dozen to a few hundred possessions.

Ratings are points per 100 possessions. Errors share one shape: `{"error": {"code", "message", "details"}}`.
"""

TAGS = [
    {"name": "catalog", "description": "Seasons and teams."},
    {"name": "lineups", "description": "Five-man lineups with pre- vs post-break ratings."},
    {"name": "players", "description": "Player on-court, on/off and usage statistics."},
    {"name": "teams", "description": "Team ratings and records; model predictions for a team's lineups."},
    {"name": "predictions", "description": "Frozen-model predictions for any five players of a team."},
    {"name": "model", "description": "Model card and evaluation results."},
    {"name": "health", "description": "Liveness / readiness."},
]


def create_app(settings: Settings | None = None, *, load_model: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = make_pool(settings)
        if app.state.pool is not None:
            app.state.pool.open(wait=False)          # connect in the background; don't block or crash startup
        app.state.predictor = None
        if load_model:
            try:
                app.state.predictor = FrozenPredictor(settings.model_dir, settings.reports_dir,
                                                      settings.require_git_freeze)
            except Exception:
                log.exception("frozen model NOT loaded; prediction endpoints will return 503")
        yield
        if app.state.pool is not None:
            app.state.pool.close()

    app = FastAPI(title="NBA Lineup Analytics API", version="1.0.0", description=DESCRIPTION,
                  openapi_tags=TAGS, lifespan=lifespan, docs_url="/docs", redoc_url="/redoc")
    app.state.settings = settings
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])
    errors.install(app)
    app.include_router(health.router)
    for r in (catalog, lineups, players, teams, predictions, model):
        app.include_router(r.router, prefix=API_PREFIX)
    return app


app = create_app()
