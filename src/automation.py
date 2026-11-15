"""Automation dispatcher for scheduled and manual searches."""

from __future__ import annotations

import argparse
import json

from .app import DB_PATH, connect, ensure_fixture_source, migrate
from .pipeline import run_search


def dispatch(dry_run: bool = False) -> dict:
    """Prepare the local database and execute one search run."""
    db = connect()
    try:
        migrate(db)
        ensure_fixture_source(db)
    finally:
        db.close()
    return run_search(dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BringMeJobs automation dispatcher")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(dispatch(args.dry_run), indent=2))


if __name__ == "__main__":
    main()
