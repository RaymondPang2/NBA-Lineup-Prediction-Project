"""Database fixtures: each test session gets a throwaway database, never the real one.

Tests marked `db` are skipped automatically when PostgreSQL isn't reachable
(e.g. on a laptop without Docker running). CI will provide a Postgres service.
"""
from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from nba_lineups.db.connection import apply_schema, database_url


def _with_db(url: str, dbname: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


@pytest.fixture(scope="session")
def test_db_url():
    try:
        admin_url = os.environ.get("TEST_DATABASE_ADMIN_URL") or database_url()
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=3)
    except (RuntimeError, psycopg.OperationalError) as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    name = f"nba_test_{uuid.uuid4().hex[:8]}"
    admin.execute(f"CREATE DATABASE {name}")
    try:
        yield _with_db(admin_url, name)
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.close()


@pytest.fixture
def conn(test_db_url):
    """Fresh schema per test: drop everything, recreate, hand over an autocommit connection."""
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        apply_schema(c)
        yield c
