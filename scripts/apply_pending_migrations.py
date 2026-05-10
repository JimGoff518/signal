"""Apply pending DDL changes to the prod database.

The migration list lives in `signalwarn.migrations.PENDING` so the FastAPI
app can apply the same statements automatically on startup. This script is
the standalone CLI form for cases where you want to run them on demand
(e.g. against a local dev DB before bringing the app up).

Usage:

    python scripts/apply_pending_migrations.py

Idempotent. Safe to re-run. Doesn't touch row data.
"""
from __future__ import annotations

import logging
import sys

# Ensure the project's `src/` is importable when this script runs directly.
sys.path.insert(0, str((__import__("pathlib").Path(__file__).resolve().parent.parent / "src")))

from signalwarn.migrations import PENDING, apply_pending  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    n = apply_pending()
    logging.getLogger("apply_migrations").info(
        "Done. %s/%s migration(s) applied.", n, len(PENDING),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
