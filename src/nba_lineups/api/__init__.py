"""Phase 7: read-only REST API over the PostgreSQL warehouse and the frozen Phase 6 model.

Run locally:  .venv/bin/uvicorn nba_lineups.api.main:app --reload     (docs at http://127.0.0.1:8000/docs)

Layout (requests flow top to bottom):
  routers/   HTTP layer: paths, query/body parameters, status codes, response models
  services/  business logic and SQL; plain functions that take a database connection
  schemas    Pydantic request/response models (the API contract, also the OpenAPI schema)
  db         connection pool (read-only sessions, statement timeout)
  errors     exception types and the handlers that turn them into a uniform JSON error body
  settings   configuration from environment variables / .env (no secrets in code)
"""
