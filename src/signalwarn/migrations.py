"""Pending DDL migrations applied on top of `migrations/001_initial_schema.sql`.

SIGNAL has no migration runner — the project convention is to land schema
changes in 001_initial_schema.sql (which only auto-applies on first boot of a
fresh DB) AND apply them by hand to existing databases. This module is the
"by hand" part, factored out so both `scripts/apply_pending_migrations.py`
and the FastAPI app's startup hook can apply them.

Every statement uses IF NOT EXISTS so re-running is safe. Append new tuples
to PENDING when you ship a future schema change.
"""
from __future__ import annotations

import logging

from signalwarn.db import connection

log = logging.getLogger(__name__)


# Each tuple: (description, SQL). Order matters when statements depend on
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
    (
        "2026-09-18 — statute-of-limitations: time-barred complaint count",
        """
        ALTER TABLE clusters
          ADD COLUMN IF NOT EXISTS time_barred_count INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    (
        "2026-09-18 — Phase 2 Texas geographic filter: per-cluster TX complaint count",
        """
        ALTER TABLE clusters
          ADD COLUMN IF NOT EXISTS tx_complaint_count INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    (
        "2026-09-18 — /investigate research addendum (Descrybe-sourced authority)",
        """
        ALTER TABLE clusters
          ADD COLUMN IF NOT EXISTS research_memo TEXT,
          ADD COLUMN IF NOT EXISTS research_generated_at TIMESTAMPTZ;
        """,
    ),
]


def apply_pending() -> int:
    """Apply every entry in PENDING. Returns the count applied.

    Safe to call on every app startup — every statement is idempotent.
    Failures are logged but don't raise, so a transient DB hiccup at boot
    doesn't take the web service down. Subsequent boots will retry.
    """
    applied = 0
    try:
        with connection() as conn:
            for desc, sql in PENDING:
                with conn.cursor() as cur:
                    cur.execute(sql)
                applied += 1
                log.info("migration applied: %s", desc)
            conn.commit()
    except Exception:
        log.exception("apply_pending failed; continuing without migration")
    return applied
