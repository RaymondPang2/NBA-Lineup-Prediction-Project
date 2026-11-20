"""Phase 9: generate the Power BI Project (TMDL semantic model + PBIR report), theme and DAX script.

    .venv/bin/python scripts/phase9/build_powerbi_project.py

Writes powerbi/ (committed: it contains definitions only, no data). Regenerate after editing
src/nba_lineups/bi/model.py or report.py; tests/powerbi checks that the committed files are up to date.
"""
from __future__ import annotations

from nba_lineups.bi import project
from nba_lineups.config import PROJECT_ROOT


def main() -> None:
    files = project.build()
    print(f"wrote {len(files)} files under {project.OUT.relative_to(PROJECT_ROOT)}/")
    print(f"wrote {project.write_docs().relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
