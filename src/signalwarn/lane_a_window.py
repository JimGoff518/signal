"""Lane A (NHTSA auto) complaint filed-date window.

Jimmy locked decision 2026-10-01 (exact-yes via CoS / Signal room): keep only
complaints whose NHTSA **filed** date is on or after calendar year 2026.
Mass Tort (Lane B) is completely untouched.

Date semantics
--------------
Filter on ``complaints.date_complaint_filed`` (Postgres DATE), which stores the
calendar date NHTSA publishes as the complaint filed date. Parsing in
``nhtsa._parse_date`` / ``flatfile`` yields a Python ``date`` with no timezone —
there is no CT/UTC conversion. Comparisons are calendar-date equality against
``LANE_A_MIN_FILED_DATE`` (2026-01-01).

NULL ``date_complaint_filed`` is treated as ineligible (same as historical
import already skipping undated rows) so the dashboard cannot retain undated
pre-window noise after the hard purge.
"""
from __future__ import annotations

from datetime import date

# Inclusive floor: keep filed dates on or after this calendar day.
LANE_A_MIN_FILED_DATE: date = date(2026, 1, 1)

# Predicate for a complaints row aliased ``c``. Bind %(lane_a_min_filed)s.
LANE_A_PRE_WINDOW_SQL = (
    "(c.date_complaint_filed IS NULL "
    "OR c.date_complaint_filed < %(lane_a_min_filed)s)"
)


def is_eligible_lane_a_filed_date(filed: date | None) -> bool:
    """True when a complaint may be ingested into Lane A."""
    return filed is not None and filed >= LANE_A_MIN_FILED_DATE


def purge_pre_window_sql() -> list[tuple[str, str]]:
    """Ordered (label, SQL) steps for the Lane A hard purge.

    Idempotent: re-running after a successful purge deletes zero rows.
    Never references mass_tort_* / mdl_events.
    """
    return [
        (
            "delete_pre_2026_complaints",
            f"""
            DELETE FROM complaints c
             WHERE {LANE_A_PRE_WINDOW_SQL}
            """,
        ),
        (
            "delete_orphan_clusters",
            """
            DELETE FROM clusters cl
             WHERE NOT EXISTS (
               SELECT 1 FROM cluster_complaints cc
                WHERE cc.cluster_id = cl.id
             )
            """,
        ),
    ]
