from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..schemas import Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health, summary="Liveness and readiness")
def health(request: Request, response: Response):
    """200 when the database answers and the frozen model is loaded and unchanged; 503 otherwise."""
    pool, predictor = request.app.state.pool, request.app.state.predictor
    database = "not_configured"
    if pool is not None:
        try:
            with pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1")
            database = "ok"
        except Exception:
            database = "unavailable"
    model = "ok" if predictor is not None and predictor.verify() else "unavailable"
    ok = database == "ok" and model == "ok"
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "degraded", "database": database, "model": model,
            "model_artifact_sha256": predictor.artifact_sha256 if predictor is not None else None}
