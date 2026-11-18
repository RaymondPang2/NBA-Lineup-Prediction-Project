"""Write the API's OpenAPI document to web/openapi.json, the single source of the frontend's TypeScript types.

    .venv/bin/python scripts/phase8/export_openapi.py          # then: cd web && npm run gen:api

The schema is built from the FastAPI app's routes and Pydantic models; no database, model or server is needed.
web/src/api/integration.test.ts checks that this committed copy still equals the live server's /openapi.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from nba_lineups.api.main import create_app

OUT = Path(__file__).resolve().parents[2] / "web" / "openapi.json"


def main() -> None:
    app = create_app(load_model=False)
    OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parents[1])} ({len(app.openapi()['paths'])} paths)")


if __name__ == "__main__":
    main()
