"""API configuration, read once at startup from environment variables (falling back to the git-ignored .env).

Nothing secret lives in code: the database URL (with its password) comes from DATABASE_URL, exactly as for
the ETL. Every other setting has a safe local default.

  DATABASE_URL                  postgresql://user:password@host:port/db   (required)
  NBA_API_CORS_ORIGINS          comma-separated browser origins allowed to call the API
                                (default: the Vite dev server, http://localhost:5173 and 127.0.0.1:5173)
  NBA_API_MODEL_DIR             frozen model directory (default: models/final)
  NBA_API_REQUIRE_GIT_FREEZE    1 (default): refuse to serve held-out seasons unless the frozen model is
                                committed to git and unchanged; 0 only where no git checkout exists (a
                                deployment image). The SHA-256 check against frozen_spec.json always runs.
  NBA_API_POOL_MIN / _MAX       connection-pool size (default 1 / 10)
  NBA_API_POOL_TIMEOUT_S        seconds to wait for a free connection before answering 503 (default 5)
  NBA_API_STATEMENT_TIMEOUT_MS  server-side limit per SQL statement (default 10000)
  NBA_DEMO_MODE                 1: the database holds the SYNTHETIC demo league (public deployment, docs/deployment.md);
                                seasons are labelled "demo" and every prediction carries a synthetic-data note
  NBA_API_STATIC_DIR            directory of the built dashboard (web/dist) to serve from the same origin (optional)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import PROJECT_ROOT
from ..db.connection import read_env_file


def _get(name: str, default: str) -> str:
    return os.environ.get(name) or read_env_file().get(name) or default


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    cors_origins: tuple[str, ...]
    model_dir: Path
    reports_dir: Path
    require_git_freeze: bool
    pool_min: int
    pool_max: int
    pool_timeout_s: float
    statement_timeout_ms: int
    demo_mode: bool = False
    static_dir: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        origins = _get("NBA_API_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        return cls(
            database_url=os.environ.get("DATABASE_URL") or read_env_file().get("DATABASE_URL"),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            model_dir=Path(_get("NBA_API_MODEL_DIR", str(PROJECT_ROOT / "models" / "final"))),
            reports_dir=Path(_get("NBA_API_REPORTS_DIR", str(PROJECT_ROOT / "reports" / "phase6"))),
            require_git_freeze=_get("NBA_API_REQUIRE_GIT_FREEZE", "1") not in ("0", "false", "False"),
            pool_min=int(_get("NBA_API_POOL_MIN", "1")),
            pool_max=int(_get("NBA_API_POOL_MAX", "10")),
            pool_timeout_s=float(_get("NBA_API_POOL_TIMEOUT_S", "5")),
            statement_timeout_ms=int(_get("NBA_API_STATEMENT_TIMEOUT_MS", "10000")),
            demo_mode=_get("NBA_DEMO_MODE", "0") in ("1", "true", "True"),
            static_dir=Path(d) if (d := _get("NBA_API_STATIC_DIR", "")) else None,
        )
