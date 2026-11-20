# REST API (Phase 7)

This is a read-only FastAPI service. It sits over the PostgreSQL warehouse and the **frozen** Phase 6 model. It serves seasons, teams, lineups, players and team statistics, plus model predictions. Every prediction comes with the team-prior baseline and its uncertainty.

## Running it

```bash
docker compose up -d                                    # PostgreSQL (data loaded by the ETL, Phases 1-2)
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn nba_lineups.api.main:app --reload     # http://127.0.0.1:8000
```

- **Interactive docs:**
  - Swagger UI at <http://127.0.0.1:8000/docs>: try every endpoint in the browser.
  - ReDoc at `/redoc`.
- **Machine-readable contract:** `/openapi.json`.
- **Health check:** `GET /health` returns 200 when the database answers and the model is loaded and unchanged, and 503 otherwise.

### Configuration
All configuration comes from environment variables, or from the git-ignored `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | none (required) | The same variable the ETL uses. It holds the only secret, and it is never logged or returned. |
| `NBA_API_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Browser origins allowed to call the API (the Vite dev server for Phase 8). |
| `NBA_API_MODEL_DIR` | `models/final` | Directory of the frozen model. |
| `NBA_API_REQUIRE_GIT_FREEZE` | `1` | Serve only if `models/final` is committed and unchanged. Set it to `0` only in a deployment image without git. The SHA-256 check always runs. |
| `NBA_API_POOL_MIN` / `_MAX` | `1` / `10` | Connection-pool size. |
| `NBA_API_POOL_TIMEOUT_S` | `5` | Wait for a free connection before answering 503. |
| `NBA_API_STATEMENT_TIMEOUT_MS` | `10000` | Server-side limit per SQL statement. A timeout answers 504. |

Pooled sessions are read-only and run without parallel query (`max_parallel_workers_per_gather=0`). The API's requests are many small concurrent reads. Parallel workers allocate shared memory, which exhausted Docker's default 64 MB `/dev/shm` under the dashboard's concurrent paging.

Predictions for the season in progress (2026-27) carry `provisional: true` and `data_cutoff`, with notes explaining why. The model's per-season cache for that season is keyed by the data version, so the first request after a refresh recomputes them; no restart is needed.

## Endpoints
Everything is under `/api/v1`. The version lives in the path so a breaking change can ship as `/api/v2` next to it.

| Method and path | Purpose |
|---|---|
| `GET /seasons` | Seasons, their break windows, irregular flag, role (`development`, `held_out`, or `current` for the season in progress) |
| `GET /data-status` | Freshness of the season in progress: last update, data cutoff, `current`/`stale`, last attempt, `data_version`. Read-only; nothing in the API triggers a refresh ([refresh.md](refresh.md)) |
| `GET /teams?season=` | Teams, optionally only those with lineups in a season |
| `GET /lineups?season=&team_id=&player_id=&min_pre_poss=&min_post_poss=&sort=&order=&page=&page_size=` | Lineups with pre- and post-break ratings and the change |
| `GET /lineups/{lineup_id}` | One lineup, plus its season total |
| `GET /lineups/{lineup_id}/prediction?possessions=&include_observed=` | Frozen-model prediction for a recorded lineup |
| `POST /predictions` | Prediction for **any** five players of one team (they need not have played together) |
| `GET /players?season=&team_id=&search=&min_pre_minutes=&sort=` | Player on-court, on/off and usage stats, one row per player and team |
| `GET /players/{player_id}?season=` | Every season and team of one player |
| `GET /teams/stats?season=` | All teams: pre- and post-break ORtg, DRtg, net and win-loss |
| `GET /teams/{team_id}/stats?season=` | One team |
| `GET /teams/{team_id}/predictions?season=&min_pre_poss=` | A team's lineups ranked by prediction, each with its baseline |
| `GET /model` | Model card: features, coefficients, artifact hash (re-verified on every call), use and limitations |
| `GET /model/performance` | Development CV and held-out results with CIs; the pre-registered verdict |

### Filtering, sorting and pagination
- **Filters:**
  - `player_id` can repeat, up to five times: it returns lineups containing **all** of those players.
  - `min_pre_poss` and `min_post_poss` apply to **both** ends (own and opponent possessions), matching the model's target sample (≥ 25 post-break possessions per end).
  - `/lineups` requires at least one of `season`, `team_id` or `player_id`, so it never returns all ~130,000 rows.
- **Sorting:**
  - `sort` accepts only listed names, for example `pre_poss`, `post_net`, `net_change` and `pre_def` on lineups.
  - `order` is `asc` or `desc`.
  - Ties are broken by id, so pages are stable.
- **Pagination:**
  - Use `page` (from 1) and `page_size` (1–200, default 50).
  - Responses are `{"items": [...], "page", "page_size", "total", "total_pages"}`.
  - The total is computed in the same query with `count(*) OVER ()`.

### Errors
Every error has one shape:
```json
{"error": {"code": "not_found", "message": "lineup 999999999 not found", "details": null}}
```

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | Valid types but an impossible request: no filter, duplicate players, a player who never played for the team that season |
| 404 | `not_found` | Unknown season, team, lineup, player or route |
| 405 | `method_not_allowed` | For example, `DELETE` anywhere |
| 422 | `validation_error` | Parameter or body fails validation (`details` lists each field) |
| 503 | `database_unavailable` / `model_unavailable` | Database down or no free connection; model not loaded |
| 504 | `query_timeout` | Statement timeout |
| 500 | `internal_error` | Bug. Details are only logged, never returned. |

## Example requests
```bash
# Oklahoma City's most-used 2025-26 lineups, with at least 200 pre-break possessions per end
curl "http://127.0.0.1:8000/api/v1/lineups?season=2025-26&team_id=1610612760&min_pre_poss=200"

# lineups in which two players played together
curl "http://127.0.0.1:8000/api/v1/lineups?season=2025-26&player_id=1630162&player_id=1630183"

# biggest post-break drops among lineups with real samples in both windows
curl "http://127.0.0.1:8000/api/v1/lineups?season=2024-25&min_pre_poss=100&min_post_poss=50&sort=net_change&order=asc"

# a recorded lineup's prediction, and what actually happened
curl "http://127.0.0.1:8000/api/v1/lineups/281112/prediction?possessions=100&include_observed=true"

# a hypothetical five
curl -X POST http://127.0.0.1:8000/api/v1/predictions -H 'Content-Type: application/json' \
     -d '{"season_id": "2025-26", "team_id": 1610612750, "player_ids": [203497, 203944, 1628978, 1630162, 1630183]}'
```

Real response for lineup 281112: Minnesota 2025-26, Gobert, Randle, DiVincenzo, Edwards, McDaniels. It is abridged, and the numbers are rounded here (the API returns them unrounded).

| | Value |
|---|---|
| Pre-break | 1,183 possessions, net **+10.0** (sampling SD 5.0) |
| **Predicted** post-break net | **+5.89** |
| Team prior (baseline) | +6.11 (model − prior = −0.22) |
| League mean | +2.87 |
| Model SD (about the true rating) | 9.55, giving a 95% interval for the true rating of −12.8 to +24.6 |
| Sampling SD at 100 possessions | 17.1 |
| Total SD | 19.6, giving a 95% interval for the observed rating of −32.5 to +44.3 |
| Observed post-break (`include_observed`) | 319 possessions, net **+0.07** |

The lineup's pre-break +10.0 is shrunk toward its team. The model and the team prior agree within 0.22 points, far inside the uncertainty. The observed post-break +0.07 fell inside both intervals. The 9.9-point drop from before the break to after is within sampling noise: `change.exceeds_noise = false`, with a change SD of 10.8.

## Predictions: what they are and are not
- **Model.** The model is the frozen artifact `models/final/model.joblib` (SHA-256 `a15b0c7f…`). It is loaded once and only ever used to predict. On startup the service refuses to run unless all of these hold:
  - the artifact hash matches `frozen_spec.json`;
  - `holdout.unlock()` succeeds, meaning the model is committed and unchanged;
  - the loaded model names the frozen features.

  `/model` and `/health` re-hash the file and fingerprint the in-memory coefficients on every call.
- **Inputs.** Features come only from `raw.load_pre_break_tables`, which reads `pre_asb` rows only and is validated. `include_observed` fetches the realized post-break result with a **separate** query, after the prediction, into its own field.
- **Estimand.** The prediction is the expected post-break net rating **if** the lineup plays after the break. It is not a forecast of whether, or how much, the lineup will be used. Every response says this in `notes`.
- **Baseline.**
  - Every prediction carries `baselines.team_prior`, the team's pre-break net rating from its *other* lineups plus a constant, and `model_minus_team_prior`.
  - Every response's notes state the held-out verdict, read live from the evaluation report: not statistically better than the team prior.
  - `/model/performance` computes `beats_team_prior` from the report's confidence interval. It is never typed in by hand.
- **In-sample flag.** `season_used_for_training = true` for 2018-19 to 2023-24. Those lineups' post-break results were training labels, so the prediction is a fitted value, not a test. Judge accuracy on 2024-25 and 2025-26.
- **Hypothetical lineups.** `POST /predictions` accepts five players who each appeared in some lineup for that team that season.
  - If the five form a recorded lineup, the result equals `GET /lineups/{id}/prediction`.
  - Otherwise the lineup has no shared history, and the model uses only team and player information (`pre_break.poss = 0`).

### Two kinds of uncertainty
A prediction ŷ can be wrong about the observed post-break rating y for two independent reasons:

  y − ŷ = (θ − ŷ) + (y − θ),  where θ = the lineup's true post-break quality

| | Field | Meaning | Value |
|---|---|---|---|
| **Predictive (model) uncertainty** | `model_sd` | How far the prediction is from the lineup's *true* quality θ. It is estimated as √(RMSE² − noise floor²) on the pooled held-out seasons, where noise floor² is the mean K·h. | 9.55 for every lineup (√(24.23² − 22.27²)) |
| **Sampling uncertainty** | `sampling_sd` | How far the *observed* rating y strays from θ after N possessions per end. It would exist even with a perfect model. | √(K·2/N) with K = 14,639: 34.2 at N = 25, 17.1 at 100, 9.9 at 300 |
| Total | `total_sd` | √(model_sd² + sampling_sd²) | 19.6 at 100 |

Two intervals follow from these:
- `true_rating_interval_95`, built from `model_sd`, answers: how good is this lineup, really?
- `observed_rating_interval_95`, built from `total_sd`, answers: what rating might we see after N possessions?

At typical sample sizes, sampling noise dominates.

**Caveats:**
- These are Normal approximations.
- `model_sd` is one average for every lineup, not lineup-specific.
- It was estimated on the same held-out seasons it describes, so its coverage has not been tested independently. The 2026-27 season would be the first independent check.
- `model_sd` uses the held-out estimate (9.55) rather than the development estimate, √(21.73² − 21.04²) = 5.43. The held-out estimate is out-of-sample for the frozen model and more conservative.

## Architecture
```
HTTP request
   │
   ▼
main.py ── create_app(): middleware (CORS, GZip), error handlers, routers, lifespan (pool + model)
   │
routers/ ── one module per resource: paths, parameter types and limits, status codes, response_model
   │          (validation happens here, before any code runs)
   ▼
deps.py ── dependency injection: a pooled read-only connection, the predictor, pagination
   │
services/ ── business logic + SQL; plain functions taking a connection, returning dicts
   │   catalog · lineups · players · teams · predictions (FrozenPredictor) · model_info
   ▼
db.py ── psycopg ConnectionPool (read-only sessions, statement timeout)  ──►  PostgreSQL views
         modeling.final / raw / features (Phase 5-6 code, imported, never modified)
```

- **Thin routers, testable services.** Routers only translate HTTP to function calls. The services don't know about HTTP, so they're reusable from scripts and tests.
- **Pydantic schemas are the contract.**
  - Input is validated: types, ranges, the season format `^\d{4}-\d{2}$`, and exactly five distinct players.
  - Output is checked against `response_model`, so an undocumented field can't leak out.
  - The same models generate `/openapi.json`.
- **Synchronous endpoints.**
  - Endpoints are plain `def`, so FastAPI runs them in a thread pool. psycopg's synchronous driver and pandas are blocking libraries, so `async def` would gain nothing and risk blocking the event loop.
  - The pool has 10 connections, and the season cache is protected by a lock.
- **Caching.** Features and predictions for a whole season (15–20k lineups) take under a second to compute. They are computed on first use and kept in memory per process. The data is static between ETL runs; restart the API after reloading data.
- **Held-out seasons.** The API serves predictions for 2024-25 and 2025-26 using a `HoldoutKey`. It can do so because the final test is finished and the frozen model can no longer change. A key admits held-out data for *reading* only. `FeatureBuilder.fit` still refuses held-out seasons, and a test proves it.

### Database access
- **A pool, not a connection per request.** Opening a PostgreSQL connection costs a TCP handshake, authentication and a server process. `psycopg_pool` keeps 1–10 connections open and lends one per request.
- **Read-only at the server.** Each session runs with `default_transaction_read_only = on`, so no bug can modify the warehouse. A test runs an `UPDATE` through the API's pool and requires it to fail.
- **Bound parameters only.** User values never enter SQL text (`%(season)s` parameters). `ORDER BY` picks from a fixed whitelist. Free-text search escapes LIKE wildcards.
- **Efficient queries.**
  - One statement filters, sorts, counts and pages.
  - Players are fetched for the page's lineups only.
  - The player filter uses the `lineup_players(player_id)` index.
  - Ratings come from the existing views (`v_lineup_window_ratings` and others), so the API and the analysis share one definition of every rating.
  - Measured locally, requests take 5–600 ms. The slowest is the player list, which computes on/off from team totals.
- **Starts while the database is down.** The pool opens in the background. `/health` reports `database: unavailable`, and data endpoints answer 503 instead of hanging.

## Tests (`tests/api/`, 70 tests)

| File | What it proves |
|---|---|
| `test_unit.py` (no database) | 422 on every kind of invalid input; uniform error bodies; database failures (down, pool exhausted, timeout, crash) mapped to 503/504/500 without leaking internals or credentials; settings and CORS; uncertainty arithmetic (reproduces the model card's ±67 / ±19); model card and performance read from the reports; OpenAPI lists every endpoint |
| `test_model_integrity.py` | Startup refuses a swapped artifact, an unfrozen spec, a spec naming other features, an uncommitted copy; the API source contains no `fit`, `dump`, `freeze`, file writes or tuning imports (AST scan); only GET plus the read-only `POST /predictions`; predictions leave the file and in-memory parameters unchanged; in-memory tampering is detected |
| `test_endpoints_real.py` (real database) | Every endpoint on real data: filters, sorting, pagination, ratings recomputed from totals, 404s; a traded player gets one row per team; **API predictions equal a fresh load of the frozen model** (1e-9) for a development and a held-out season; **served predictions reproduce the recorded held-out RMSEs** to 4 decimals (24.2326 pooled); hypothetical lineups; an SQL audit while building predictions sees only `pre_asb` statements and never `last_team_id`; held-out loaders still refuse without a key; sessions are read-only |

```bash
.venv/bin/python -m pytest tests/api         # real-database tests skip when PostgreSQL is down
```

## Connecting the React frontend (Phase 8)
The dashboard in `web/` follows these rules; see [docs/dashboard.md](dashboard.md).
- **Base URL:** `http://127.0.0.1:8000/api/v1`, taken from an environment variable such as `VITE_API_BASE_URL`.
- **CORS:** the Vite dev origin `http://localhost:5173` is allowed by default. Add production origins with `NBA_API_CORS_ORIGINS`.
- **Typed client:** generate TypeScript types from the contract instead of writing them by hand, for example `npx openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/schema.ts`.
- **Display:** show the prediction, its baseline and intervals together. The UI should never display a bare point prediction.

## Concepts
- **REST.** Resources (seasons, lineups, players) have URLs, and you act on them with standard HTTP methods. The server keeps no session state between requests, and responses are representations of the resources (JSON here). Filtering, sorting and pagination are query parameters on a collection URL.
- **HTTP methods.**
  - `GET` is *safe*: it changes nothing. It is also *idempotent*: repeating it has the same effect. Responses can be cached.
  - `POST` sends a body. Here `POST /predictions` is used because five player ids and options are a structured input, not because anything is created. The handler is still read-only and deterministic.
  - `PUT`, `PATCH` and `DELETE` would modify resources. This API has none, so they return 405.
- **Status codes** say what happened, so clients can branch on them:
  - 2xx: success;
  - 4xx: the client's mistake (400, 404, 422);
  - 5xx: the server's problem (500, 503, 504).
- **Pydantic** turns Python type hints into runtime validation and JSON Schema.
  - `Field(ge=10, le=3000)` and `field_validator` enforce rules at the boundary, before any code runs, so business logic can trust its inputs.
  - FastAPI uses the same models to filter responses and generate the OpenAPI docs.
- **Dependency injection.** Endpoints declare what they need (`conn: Conn`, `predictor: Predictor`), and FastAPI supplies it per request. Tests replace a dependency with `app.dependency_overrides`, for example a database that always fails, without changing endpoint code.
- **PostgreSQL integration:**
  - connection pooling;
  - server-side read-only transactions and statement timeouts;
  - bound parameters, which prevent SQL injection;
  - window functions (`count(*) OVER ()`) for pagination totals;
  - indexes matching the filters;
  - views as the single definition of derived metrics.
- **Layered backend architecture.** Routers handle HTTP, services hold logic and SQL, and the database layer manages connections. Each layer has one reason to change, so each can be tested on its own. The application-factory pattern (`create_app(settings)`) lets tests build an app with different settings.
