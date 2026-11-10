"""Raw data ingestion from stats.nba.com (the 'bronze' layer).

Modules:
    windows   -- derive pre/post All-Star-break date windows from game dates
    specs     -- describe each API request as an immutable RequestSpec
    client    -- HTTP transport, rate limiting, retries with backoff
    storage   -- atomic JSON writes and safe reads
    validate  -- structural and semantic checks on raw payloads
    manifest  -- append-only JSONL log of every fetch attempt
    pipeline  -- orchestration: cache-aware, resumable ingestion
    cli       -- command-line entry point (python -m nba_lineups.ingest)
"""
