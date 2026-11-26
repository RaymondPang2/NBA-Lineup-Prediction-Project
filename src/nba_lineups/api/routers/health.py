from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..schemas import Health

router = APIRouter(tags=["health"])


def demo_ready(conn) -> bool:
    from ...demo.league import DEMO_SEASONS          # every demo season loaded (a partial seed is not ready)
    if conn.execute("SELECT to_regclass('seasons') IS NULL").fetchone()[0]:
        return False
    have = {r[0] for r in conn.execute("SELECT season_id FROM seasons")}
    return set(DEMO_SEASONS) <= have


@router.get("/health", response_model=Health, summary="Liveness and readiness")
def health(request: Request, response: Response):
    """200 when the database answers and the frozen model is loaded and unchanged; 503 otherwise."""
    pool, predictor = request.app.state.pool, request.app.state.predictor
    database = "not_configured"
    if pool is not None:
        try:
            with pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1")
                if request.app.state.settings.demo_mode and not demo_ready(conn):
                    database = "seeding"           # demo: the synthetic league is still being built
                else:
                    database = "ok"
        except Exception:
            database = "unavailable"
    model = "ok" if predictor is not None and predictor.verify() else "unavailable"
    ok = database == "ok" and model == "ok"
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "degraded", "mode": "demo" if request.app.state.settings.demo_mode else "full",
            "database": database, "model": model,
            "model_artifact_sha256": predictor.artifact_sha256 if predictor is not None else None}
