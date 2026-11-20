"""API test fixtures.

`offline_client`: no database at all (DATABASE_URL unset); the frozen model is loaded. Unit tests of
validation, errors, uncertainty and the model card run anywhere.

`client`: the real, populated development database, through the API's READ-ONLY pool (the API cannot write;
test_endpoints_real.py proves it). Skipped when PostgreSQL or the loaded seasons are missing.
"""
from __future__ import annotations

import dataclasses

import psycopg
import pytest
from fastapi.testclient import TestClient

from nba_lineups.api import deps
from nba_lineups.api.errors import DatabaseUnavailable
from nba_lineups.api.main import create_app
from nba_lineups.api.settings import Settings
from nba_lineups.config import ALL_SEASONS


@pytest.fixture(scope="session")
def offline_settings() -> Settings:
    return dataclasses.replace(Settings.from_env(), database_url=None)


class NoDatabase:
    """Stands in for a connection: any use raises DatabaseUnavailable (503), like a missing database.
    Lets validation tests reach parameter validation, which FastAPI runs after dependencies."""

    def __getattr__(self, name):
        raise DatabaseUnavailable("no database in offline tests")


def _no_db():
    yield NoDatabase()


@pytest.fixture(scope="session")
def offline_client(offline_settings):
    app = create_app(offline_settings)
    app.dependency_overrides[deps.get_conn] = _no_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def real_settings() -> Settings:
    s = Settings.from_env()
    if not s.database_url:
        pytest.skip("DATABASE_URL not set")
    try:
        with psycopg.connect(s.database_url, connect_timeout=3) as c:
            seasons = [r[0] for r in c.execute("SELECT season_id FROM seasons ORDER BY 1")]
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    if not set(ALL_SEASONS) <= set(seasons):
        pytest.skip(f"database does not hold the eight production seasons (has {seasons})")
    return s


@pytest.fixture(scope="session")
def client(real_settings):
    with TestClient(create_app(real_settings), raise_server_exceptions=False) as c:
        c.app.state.pool.wait(timeout=10)
        yield c


@pytest.fixture(scope="session")
def predictor(client):
    return client.app.state.predictor
