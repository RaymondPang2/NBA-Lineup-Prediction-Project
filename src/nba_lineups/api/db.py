"""PostgreSQL connection pool for the API.

Why a pool: opening a PostgreSQL connection costs a TCP handshake, authentication and a server process
(milliseconds each time). The pool keeps a few connections open and lends one to each request.

Every pooled session is READ-ONLY (`default_transaction_read_only = on`): the API cannot insert, update or
delete anything, even through a bug. A `statement_timeout` stops a runaway query on the server side.
The pool opens lazily and in the background, so the app starts (and /health answers) while the database is
down; requests that need it then fail with 503 instead of hanging.
"""
from __future__ import annotations

from collections.abc import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .errors import DatabaseUnavailable
from .settings import Settings


def make_pool(settings: Settings) -> ConnectionPool | None:
    if not settings.database_url:
        return None
    # No parallel query: API requests are many small concurrent reads, and each parallel worker allocates
    # dynamic shared memory; under the dashboard's concurrent paging that exhausted Docker's default 64 MB
    # /dev/shm ("could not resize shared memory segment"), so serial plans are both safer and fast enough.
    options = (f"-c default_transaction_read_only=on -c statement_timeout={settings.statement_timeout_ms} "
               "-c max_parallel_workers_per_gather=0")
    return ConnectionPool(settings.database_url, min_size=settings.pool_min, max_size=settings.pool_max,
                          timeout=settings.pool_timeout_s, open=False, name="nba-api",
                          kwargs={"options": options, "connect_timeout": 3, "application_name": "nba-lineups-api"})


def connection(pool: ConnectionPool | None) -> Iterator[psycopg.Connection]:
    """Lend a connection for one request; it is returned to the pool (and its transaction ended) afterwards."""
    if pool is None:
        raise DatabaseUnavailable("DATABASE_URL is not configured")
    with pool.connection() as conn:
        yield conn


def fetch_all(conn: psycopg.Connection, sql: str, params: dict | None = None) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def fetch_one(conn: psycopg.Connection, sql: str, params: dict | None = None) -> dict | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None
