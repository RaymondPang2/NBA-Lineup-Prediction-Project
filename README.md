# NBA Lineup Analytics & Prediction Platform

Analyzes historical NBA five-player lineup performance and predicts post-All-Star-break lineup net rating with leak-free, chronologically validated models.

**Status:** Phase 8 (React + TypeScript dashboard over the API, [docs/dashboard.md](docs/dashboard.md)) complete, awaiting review. Phase 7 provides the read-only FastAPI service over the warehouse and the frozen model ([docs/api.md](docs/api.md)). Phase 6 headline: on the held-out 2024-25 and 2025-26 seasons the frozen model beats the league mean but is statistically indistinguishable from a simple team-strength baseline, because the target is dominated by measurement noise (see the [model card](docs/model_card.md)). See [docs/project_plan.md](docs/project_plan.md).

| Doc | Contents |
|---|---|
| [docs/phase0_data_report.md](docs/phase0_data_report.md) | Data availability, the API row cap, selection bias, first signal check |
| [docs/ingestion.md](docs/ingestion.md) | Ingestion pipeline, validation rules, sample-size gate |
| [docs/database.md](docs/database.md) | Schema, constraints, ETL rules, DQ checks, possession-definition finding |
| [docs/metrics.md](docs/metrics.md) | Rating definitions, exact opponent possessions, validation against NBA values |
| [docs/eda_reliability.md](docs/eda_reliability.md) | Distributions, measurement model, split-half reliability, EB shrinkage, selection model ([figures](reports/phase4/figures)) |
| [docs/features_baselines.md](docs/features_baselines.md) | Feature dictionary, leakage audit, expanding-window CV, baselines vs the noise floor ([figures](reports/phase5/figures)) |
| [docs/modeling.md](docs/modeling.md) | Nested CV of linear / ridge / random forest, interpretability, freeze protocol, final held-out test ([figures](reports/phase6/figures)) |
| [docs/model_card.md](docs/model_card.md) | Model card: estimand, performance, appropriate use, limitations |
| [docs/api.md](docs/api.md) | REST API: endpoints, examples, prediction uncertainty, architecture, tests, frontend setup |
| [docs/dashboard.md](docs/dashboard.md) | Web dashboard: pages, how the analytical contract is kept in the UI, architecture, tests |

## Setup (macOS)
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env                       # then set a password
docker compose up -d                       # PostgreSQL 17.6 on 127.0.0.1:5432

.venv/bin/python -m nba_lineups.ingest --seasons 2018-19 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26
.venv/bin/python -m nba_lineups.ingest --location-splits --seasons 2018-19 2019-20 2020-21 2021-22 2022-23 2023-24
.venv/bin/python -m nba_lineups.etl        # bronze JSON -> PostgreSQL (idempotent)
.venv/bin/python scripts/phase4/eda_reliability.py   # Phase 4 figures + reports/phase4/findings.json
.venv/bin/python -m nba_lineups.modeling.build       # Phase 5 feature table + manifest (data/features/)
.venv/bin/python scripts/phase5/features_baselines.py  # Phase 5 feature quality + baseline CV (reports/phase5/)
.venv/bin/python scripts/phase6/train_evaluate.py      # Phase 6 nested CV, selection, freeze (models/final/)
.venv/bin/python scripts/phase6/holdout_evaluation.py  # Phase 6 final test (needs the committed freeze)
.venv/bin/uvicorn nba_lineups.api.main:app --reload    # API on http://127.0.0.1:8000 (Swagger UI at /docs)
.venv/bin/python -m pytest                 # 240+ tests; DB tests auto-skip if Postgres is down

cd web && npm install && cp .env.example .env.local   # Phase 8 dashboard (Node 20+)
npm run dev                                # http://localhost:5173 (needs the API on :8000)
npm run fixtures && npm test               # unit/component tests on fixtures recorded from the live API
npm run test:integration && npm run test:e2e   # live API integration + Playwright end-to-end
```
Run ingestion from a non-cloud IP, because stats.nba.com blocks many datacenter ranges.

## Data & attribution
The statistics come from [NBA.com/stats](https://www.nba.com/stats) through the open-source [`nba_api`](https://github.com/swar/nba_api) client. This is a personal, non-commercial educational project. Raw data isn't committed to this repository. NBA data is owned by the NBA and subject to the [NBA.com Terms of Use](https://www.nba.com/terms).
