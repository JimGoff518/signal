"""Apply pending DDL changes to the prod database.

SIGNAL has no migration runner — the project convention is to land schema
changes in `migrations/001_initial_schema.sql` (which only auto-applies on
first boot of a fresh DB) AND apply them by hand to existing databases.

This script is the "by hand" part: it runs the same ALTER TABLE / CREATE
INDEX statements from the schema file that postdate the original deploy, so
you can bring an existing DB up to date with a single command. Every
statement uses IF NOT EXISTS so re-running is safe.

Usage (must be run from inside Railway because the prod DB hostname doesn't
resolve from a developer laptop):

    railway ssh
    python scripts/apply_pending_migrations.py

Idempotent. Safe to re-run. Doesn't touch row data.
"""
from __future__ import annotations

import logging
import sys

# Ensure the project's `src/` is importable when this script runs directly.
sys.path.insert(0, str((__import__("pathlib").Path(__file__).resolve().parent.parent / "src")))

from signalwarn.db import connection  # noqa: E402

# Each tuple: (description, SQL). Append new entries here when you ship a
# schema change post-initial-deploy. Order matters when statements depend on
# each other; otherwise they're applied in list order.
PENDING: list[tuple[str, str]] = [
    (
        "2026-05-09 — CourtListener Phase 3a columns + index",
        """
        ALTER TABLE clusters
          ADD COLUMN IF NOT EXISTS class_action_url TEXT,
          ADD COLUMN IF NOT EXISTS class_action_checked_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS class_action_case_name TEXT,
          ADD COLUMN IF NOT EXISTS class_action_court TEXT,
          ADD COLUMN IF NOT EXISTS class_action_filed_date DATE;
        CREATE INDEX IF NOT EXISTS idx_clusters_class_action_filed
          ON clusters (class_action_filed) WHERE class_action_filed = TRUE;
        """,
    ),
    (
        "2026-05-09 — CourtListener case status (pending vs terminated)",
        """
        ALTER TABLE clusters
          ADD COLUMN IF NOT EXISTS class_action_status TEXT,
          ADD COLUMN IF NOT EXISTS class_action_terminated_date DATE;
        CREATE INDEX IF NOT EXISTS idx_clusters_class_action_status
          ON clusters (class_action_status) WHERE class_action_status IS NOT NULL;
        """,
    ),
]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("apply_migrations")

    with connection() as conn:
        for desc, sql in PENDING:
            log.info("Applying: %s", desc)
            with conn.cursor() as cur:
                cur.execute(sql)
        conn.commit()
    log.info("Done. %s migration(s) applied.", len(PENDING))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
