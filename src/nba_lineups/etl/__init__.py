"""Bronze (raw JSON) -> silver (PostgreSQL) ETL.

    extract   -- read one season's raw files; fail if any expected file is missing
    transform -- clean, merge name-variant rows, join measures, shape into table-ready frames
    load      -- per-season transaction: upsert dimensions, replace facts (COPY), run DQ, commit
    dq        -- SQL data-quality and reconciliation checks
    cli       -- python -m nba_lineups.etl
"""
