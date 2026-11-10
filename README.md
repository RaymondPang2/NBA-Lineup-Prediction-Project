# NBA Lineup Analytics & Prediction Platform

Analyzes historical NBA five-player lineup performance and predicts post-All-Star-break lineup net rating with leak-free, chronologically validated models.

**Status:** Phase 0 (setup + data verification). See [docs/phase0_data_report.md](docs/phase0_data_report.md) and [docs/project_plan.md](docs/project_plan.md).

## Setup (macOS)
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/phase0/fetch_spike.py     # needs a non-cloud IP; caches to data/raw/
.venv/bin/python scripts/phase0/analyze_spike.py   # offline
```

## Data & attribution
The statistics come from [NBA.com/stats](https://www.nba.com/stats) through the open-source [`nba_api`](https://github.com/swar/nba_api) client. This is a personal, non-commercial educational project. Raw data is not committed to this repository. NBA data is owned by the NBA and subject to the [NBA.com Terms of Use](https://www.nba.com/terms).
