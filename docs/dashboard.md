# Dashboard (Phase 8)

"Lineup Lab" is a React + TypeScript web app over the read-only Phase 7 API ([docs/api.md](api.md)). It has six pages: an overview, a lineup explorer, lineup detail, predictions, insights and model performance. Every number on screen comes from a live API response. The app contains no hard-coded statistics.

## Running it

You need three processes: PostgreSQL, the API and the web app.

```bash
docker compose up -d                                         # PostgreSQL (warehouse loaded by the ETL)
.venv/bin/uvicorn nba_lineups.api.main:app --port 8000       # API   http://127.0.0.1:8000  (Swagger: /docs)

cd web
npm install                                                  # first time only
cp .env.example .env.local                                   # first time only: VITE_API_BASE_URL
npm run dev                                                  # app   http://localhost:5173
```

The app must be served on port 5173. That is the origin the API allows by default (`NBA_API_CORS_ORIGINS`). `vite preview` uses the same port.

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | The API's versioned base URL. It is read at build time. A trailing `/api/v1` is optional, because the client derives the origin from it. For a public deployment, point it at the deployed API and add the site's origin to the API's `NBA_API_CORS_ORIGINS`. |

## Pages

| Route | What it shows | Endpoints |
|---|---|---|
| `/` Overview | Season and team filters; season KPIs, with league ORtg pooled from summed team totals; team pre- vs post-break scatter; season history; sortable team table; a team's most-used lineups | `/seasons`, `/teams`, `/teams/stats` (every season, for history), `/lineups` |
| `/lineups` Explorer | Server-side sorting on every rating column; pagination (25–200 rows); team filter; player search (up to 5 players, combobox over `/players?search=`); pre- and post-break possession thresholds (applied to both ends); ✱ marks changes larger than sampling noise | `/lineups`, `/players`, `/players/{id}` |
| `/lineups/:id` Detail | ORtg, DRtg and net for pre-break, post-break and the full season; net rating with 95% sampling intervals; noise test on the pre→post change; links to the prediction and to each player's lineups | `/lineups/{id}`, `/seasons` |
| `/predict` Predict | Pick a recorded lineup, or build any five players. Shows the model prediction, **team-prior baseline**, league mean, **both 95% intervals** (true quality; observed rating at N possessions, adjustable with a slider), feature contributions, pre-break evidence, the API's notes, and optionally the realized post-break result | `/lineups`, `/lineups/{id}/prediction`, `POST /predictions`, `/players` |
| `/insights` Insights | Rating distributions (net, ORtg or DRtg; pre or post); reliability funnel with the sampling-noise band; regression to the mean (pre vs post with a weighted fit); per-lineup reliability from the model API; historical performance by season | `/lineups` (paged through), `/teams/{id}/predictions`, `/teams/stats` |
| `/model` Model | Pre-registered verdict against the team prior and the league mean; RMSE by method with CIs (including the noise floor); paired differences; R² against its ceiling; calibration; all metrics; standardized coefficients; selection; verified artifact hash; use, misuse and limitations | `/model/performance`, `/model` |

Filters are kept in the URL, so every view can be linked to, survives a reload, and works with the back button. The selected season carries across pages.

## How the analytical contract is kept in the UI

- **Conditional estimand.** Every prediction is shown inside a *Conditional prediction* notice: "if its coach plays it after the break". The predict page and the model page also show it on their own, and the API's `notes` are listed verbatim.
- **Never a bare prediction.** `PredictionResult` renders the prediction only together with `baselines.team_prior`, `model_minus_team_prior`, both intervals and their SDs. A runtime guard, `isDisplayablePrediction`, withholds the number if any of them is missing or not finite. A unit test covers this.
- **The verdict is visible.** The model is not statistically better than the team prior. The prediction notice says so, and the model page leads with it. The page reads `beats_team_prior` and the conclusion text from the API; they are not written into the frontend.
- **In-sample flag.** Predictions for 2018-19 to 2023-24 carry an *In-sample season* badge and a *Fitted value, not a test* warning.
- **Realized results stay separate.** The realized post-break result is fetched only on request (`include_observed`) and is shown in its own section, labelled *never a model input*.
- **Possession denominators.** Pooled ratings in the UI (league ORtg, history) sum totals and then divide (`lib/stats.ts pooledRatings`). Ratings are never averaged. A test checks this against the API's team ratings.
- **Noise model.** The funnel band uses the backend's own K, recovered from the API's per-lineup sampling SDs (median of SD² ÷ (1/poss + 1/opp_poss) = 14,639). Nothing is re-estimated.

## Architecture

```
web/
  openapi.json                 # exported from the FastAPI app: scripts/phase8/export_openapi.py
  src/api/schema.d.ts          # generated: npm run gen:api (openapi-typescript)
  src/api/client.ts            # openapi-fetch client typed by schema.d.ts; ApiError for the uniform error body
  src/api/hooks.ts             # TanStack Query hooks: one per endpoint, cached for the session (data is static)
  src/lib/                     # formatting, statistics, URL state, feature labels
  src/components/ui/           # cards, stats, controls, tables, loading / error / empty states
  src/components/charts/       # Recharts charts + hand-drawn SVG (dot-whisker, interval) where exact control matters
  src/components/prediction/   # EstimandNotice, PredictionResult, IntervalChart, ContributionsChart
  src/pages/                   # one lazily loaded module per route
```

- **Types come from the API.** `openapi.json` is exported directly from the FastAPI app, so the export needs no server or database. `openapi-typescript` turns it into `schema.d.ts`, and `openapi-fetch` checks every request's path, parameters and body against it at compile time. The integration suite fails if the committed `openapi.json` differs from the live server's.

  To regenerate after an API change:
  ```bash
  .venv/bin/python scripts/phase8/export_openapi.py && (cd web && npm run gen:api)
  ```
- **States.** Every data view shows loading skeletons, an error panel and an empty state:
  - The error panel recognises the API's error codes. When the API is unreachable, it shows the command that starts the API. When the database is down, it shows `docker compose up -d`. It also offers a retry.
  - Network errors, 503 and 504 are retried automatically; 4xx errors are not.
  - The header shows API health, polled every 30 s.
- **Charts.**
  - Recharts draws distributions, scatters, lines and bars. Hand-drawn SVG is used for the prediction-interval and dot-and-whisker charts, where the axis must not start at zero and the intervals must be exact.
  - Every chart has a **Chart / Table** switch that shows the same values as text.
  - Charts with two or more series have a legend, and the season-history lines are also labelled directly.
  - Colors come from a validated categorical palette (blue, orange and aqua; CVD-safe across all pairs in light and dark modes), with separate light and dark values.
  - Diverging bars use blue for positive and red for negative.
- **Responsive and accessible.**
  - Layouts adapt from 390 px phones to wide desktops, and tables scroll inside their cards rather than the page scrolling sideways.
  - The theme is light, dark or system.
  - There is a skip link, ARIA roles on the comboboxes, list boxes, switches and sortable headers, and visible focus rings.
  - Motion is reduced when the OS asks for it.
- **Bundle.** Pages are code-split, and Recharts is in its own chunk.

## Tests

| Command | What it runs | Needs |
|---|---|---|
| `npm test` | 35 unit and component tests (Vitest, Testing Library, MSW): formatting; pooled-rating arithmetic; K recovery; the API client's error handling; the prediction guarantees (baseline, intervals, estimand, withholding, in-sample flag); and every page — filters, server-side sort and pagination, player search, empty, error and not-found states, the build-a-five flow | Fixtures recorded by `npm run fixtures` |
| `npm run test:integration` | 16 tests that run the app's own client against the **live** API: OpenAPI drift, health and the verified artifact, CORS for the app's origin, error shape, filter, sort and paging semantics, every-row paging for charts, prediction invariants (intervals = ŷ ± 1.96·SD, contributions sum to ŷ, estimand in the notes), the documented example (lineup 281112), hypothetical and recorded fives, consistency of the verdict with its CI | API + PostgreSQL |
| `npm run test:e2e` | 14 Playwright tests in a real browser against the live stack: each page's rendered values equal the API's; sorting, paging and player filtering; the prediction flow and the realized-result toggle; the build-a-five flow; chart and table views; no horizontal scroll at phone width on every page; mobile navigation | API + PostgreSQL; starts Vite itself |

All three suites pass (35 + 16 + 14).

**Fixtures are real API responses, and they are not committed.** `npm run fixtures` records 25 responses from the running API into `web/src/test/fixtures/`, with a manifest of each request. They are NBA-derived processed data, which the project never commits (see `.gitignore`), so the folder is git-ignored. If a fixture is missing, the tests fail with an instruction to record them. Phase 10's CI will need a way to provide them, for example by recording them from the API inside CI.

Other checks: `npm run typecheck` (strict TypeScript across the app, tests and e2e) and `npm run lint` (oxlint: 0 errors, 10 Fast Refresh and state-sync warnings).
