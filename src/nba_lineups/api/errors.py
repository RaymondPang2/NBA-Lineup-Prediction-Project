"""Errors and their HTTP mapping. Every error response has the same JSON shape:

    {"error": {"code": "not_found", "message": "season 1999-00 not found", "details": null}}

Clients branch on the stable `code`; `message` is for humans. Internal details (SQL, stack traces,
connection strings) are logged server-side and never returned.
"""
from __future__ import annotations

import logging

import psycopg
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("nba_lineups.api")


class APIError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: object | None = None):
        super().__init__(message)
        self.message, self.details = message, details


class NotFound(APIError):
    status_code, code = 404, "not_found"


class BadRequest(APIError):
    status_code, code = 400, "bad_request"


class DatabaseUnavailable(APIError):
    status_code, code = 503, "database_unavailable"


class ModelUnavailable(APIError):
    status_code, code = 503, "model_unavailable"


def _body(status: int, code: str, message: str, details: object | None = None) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, "details": jsonable_encoder(details)}})


def install(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api(_: Request, exc: APIError):
        return _body(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"location": list(e.get("loc", ())), "message": e.get("msg"), "type": e.get("type")}
                   for e in exc.errors()]
        return _body(422, "validation_error", "request parameters failed validation", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _body(exc.status_code, code, str(exc.detail))

    @app.exception_handler(psycopg.errors.QueryCanceled)
    async def _timeout(_: Request, exc: Exception):
        log.warning("query cancelled: %s", exc)
        return _body(504, "query_timeout", "the database query took too long")

    @app.exception_handler(psycopg.OperationalError)
    async def _db_down(_: Request, exc: Exception):
        log.error("database error: %s", exc)
        return _body(503, "database_unavailable", "the database is unavailable; try again later")

    @app.exception_handler(PoolTimeout)
    async def _pool(_: Request, exc: Exception):
        log.error("connection pool timeout: %s", exc)
        return _body(503, "database_unavailable", "no database connection available; try again later")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return _body(500, "internal_error", "internal server error")
