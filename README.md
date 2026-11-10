# NBA Lineup Analytics & Prediction Platform

Analyzes historical NBA five-player lineup performance and predicts post-All-Star-break lineup net rating with leak-free, chronologically validated models.

**Status:** Phase 2 (PostgreSQL silver layer) complete. See [docs/project_plan.md](docs/project_plan.md).

| Doc | Contents |
|---|---|
| [docs/phase0_data_report.md](docs/phase0_data_report.md) | Data availability, the API row cap, selection bias, first signal check |
| [docs/ingestion.md](docs/ingestion.md) | Ingestion pipeline, validation rules, sample-size gate |
| [docs/database.md](docs/database.md) | Schema, constraints, ETL rules, DQ checks, possession-definition finding |

## Setup (macOS)
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env                       # then set a password
docker compose up -d                       # PostgreSQL 17.6 on 127.0.0.1:5432

.venv/bin/python -m nba_lineups.ingest --seasons 2018-19 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26
.venv/bin/python -m nba_lineups.etl        # bronze JSON -> PostgreSQL (idempotent)
.venv/bin/python -m pytest                 # 69+ tests; DB tests auto-skip if Postgres is down
```
Run ingestion from a non-cloud IP, because stats.nba.com blocks many datacenter ranges.

## Data & attribution
The statistics come from [NBA.com/stats](https://www.nba.com/stats) through the open-source [`nba_api`](https://github.com/swar/nba_api) client. This is a personal, non-commercial educational project. Raw data isn't committed to this repository. NBA data is owned by the NBA and subject to the [NBA.com Terms of Use](https://www.nba.com/terms).
