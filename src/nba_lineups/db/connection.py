"""Database connection and schema helpers.

The connection URL comes from the DATABASE_URL environment variable, falling
back to the git-ignored .env file. Credentials never appear in source code.
"""
from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

import psycopg

from ..config import PROJECT_ROOT

# Dropped in dependency order (children before parents) by reset_schema().
TABLES = ("lineup_window_stats", "player_window_stats", "team_window_stats", "lineup_players", "lineups",
          "team_games", "stat_windows", "players", "teams", "seasons", "ingestion_log", "etl_runs")


def read_env_file(path: Path = PROJECT_ROOT / ".env") -> dict[str, str]:
    """Minimal KEY=VALUE parser (avoids adding python-dotenv as a dependency)."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def database_url() -> str:
    url = os.environ.get("DATABASE_URL") or read_env_file().get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (environment or .env). See .env.example.")
    return url


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    return psycopg.connect(url or database_url(), **kwargs)


def apply_schema(conn: psycopg.Connection) -> None:
    """Create all tables/views if missing. Idempotent."""
    conn.execute(files("nba_lineups.db").joinpath("schema.sql").read_text())


def reset_schema(conn: psycopg.Connection) -> None:
    """Drop and recreate every project table. Destroys loaded data (bronze files are untouched)."""
    conn.execute("DROP VIEW IF EXISTS v_lineup_window_ratings")
    for table in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    apply_schema(conn)
