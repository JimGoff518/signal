"""One-shot Lane A hard purge of pre-2026 NHTSA complaints.

See ``lane_a_window`` for the locked filed-date window. This module is the
runtime side of ``migrations/003_purge_pre_2026_lane_a.sql`` /
``scripts/purge_pre_2026_lane_a.py``. It is **not** registered in
``migrations.PENDING`` so FastAPI startup will never auto-run a destructive
delete against production.

Delete order (FK-safe):
  1. DELETE complaints with filed date before 2026-01-01 (or NULL).
     ``cluster_complaints`` rows cascade via ON DELETE CASCADE.
  2. DELETE clusters with no remaining memberships.
     ``alerts_sent`` cascades; viability/research memos live on the cluster
     row so they go with the orphan.
  3. Recalculate aggregates on every surviving cluster that still has members
     (counts / year-span shrink to remaining 2026 siblings).

Mass Tort tables (``mass_tort_matters``, ``mdl_events``) are never referenced.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from signalwarn.clustering import recalculate_cluster
from signalwarn.db import connection
from signalwarn.lane_a_window import LANE_A_MIN_FILED_DATE, LANE_A_PRE_WINDOW_SQL, purge_pre_window_sql

log = logging.getLogger(__name__)

# Tables this purge is allowed to mutate. Used by tests as a hard allow-list.
LANE_A_PURGE_TABLES = frozenset({"complaints", "clusters", "cluster_complaints", "alerts_sent"})
MASS_TORT_TABLES = frozenset({"mass_tort_matters", "mdl_events"})


@dataclass
class PurgeResult:
    dry_run: bool
    complaints_matched: int = 0
    complaints_deleted: int = 0
    orphan_clusters_matched: int = 0
    orphan_clusters_deleted: int = 0
    clusters_recalculated: int = 0
    mass_tort_matters_before: int | None = None
    mass_tort_matters_after: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def mass_tort_untouched(self) -> bool:
        if self.mass_tort_matters_before is None or self.mass_tort_matters_after is None:
            return True
        return self.mass_tort_matters_before == self.mass_tort_matters_after


def _count(cur, sql: str, params: dict | None = None) -> int:
    cur.execute(sql, params or {})
    row = cur.fetchone()
    return int(row["n"] if isinstance(row, dict) else row[0])


def preview_purge(conn) -> dict[str, int]:
    """Return counts that would be affected without mutating."""
    params = {"lane_a_min_filed": LANE_A_MIN_FILED_DATE}
    with conn.cursor() as cur:
        complaints = _count(
            cur,
            f"SELECT COUNT(*) AS n FROM complaints c WHERE {LANE_A_PRE_WINDOW_SQL}",
            params,
        )
        # Orphans after those complaints are removed (estimate via anti-join).
        orphans = _count(
            cur,
            f"""
            SELECT COUNT(*) AS n FROM clusters cl
             WHERE NOT EXISTS (
               SELECT 1 FROM cluster_complaints cc
                JOIN complaints c ON c.id = cc.complaint_id
                WHERE cc.cluster_id = cl.id
                  AND NOT ({LANE_A_PRE_WINDOW_SQL})
             )
            """,
            params,
        )
        mt = _count(cur, "SELECT COUNT(*) AS n FROM mass_tort_matters")
    return {
        "complaints_matched": complaints,
        "orphan_clusters_matched": orphans,
        "mass_tort_matters": mt,
    }


def run_purge(*, dry_run: bool = True, rescore: bool = True) -> PurgeResult:
    """Execute (or preview) the Lane A pre-2026 purge.

    ``dry_run=True`` (default) only counts. Pass ``dry_run=False`` to DELETE.
    """
    result = PurgeResult(dry_run=dry_run)
    params = {"lane_a_min_filed": LANE_A_MIN_FILED_DATE}

    with connection() as conn:
        preview = preview_purge(conn)
        result.complaints_matched = preview["complaints_matched"]
        result.orphan_clusters_matched = preview["orphan_clusters_matched"]
        result.mass_tort_matters_before = preview["mass_tort_matters"]

        if dry_run:
            result.mass_tort_matters_after = result.mass_tort_matters_before
            result.notes.append("dry_run — no rows deleted")
            return result

        # Guard: every SQL step must stay inside the Lane A allow-list.
        for label, sql in purge_pre_window_sql():
            lowered = sql.lower()
            for banned in MASS_TORT_TABLES:
                if banned in lowered:
                    raise RuntimeError(f"purge step {label} references {banned}")

        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM complaints c WHERE {LANE_A_PRE_WINDOW_SQL}",
                params,
            )
            result.complaints_deleted = cur.rowcount

            cur.execute(
                """
                DELETE FROM clusters cl
                 WHERE NOT EXISTS (
                   SELECT 1 FROM cluster_complaints cc
                    WHERE cc.cluster_id = cl.id
                 )
                """
            )
            result.orphan_clusters_deleted = cur.rowcount

            result.mass_tort_matters_after = _count(
                cur, "SELECT COUNT(*) AS n FROM mass_tort_matters"
            )

            surviving_ids: list[int] = []
            if rescore:
                cur.execute("SELECT id FROM clusters ORDER BY id")
                surviving_ids = [r["id"] for r in cur.fetchall()]

        conn.commit()

        if not result.mass_tort_untouched:
            raise RuntimeError(
                "mass_tort_matters row count changed during Lane A purge — abort semantics"
            )

        if rescore and surviving_ids:
            for cid in surviving_ids:
                recalculate_cluster(conn, cid)
            conn.commit()
            result.clusters_recalculated = len(surviving_ids)

    log.info(
        "Lane A purge complete: deleted_complaints=%s deleted_orphan_clusters=%s "
        "rescored=%s mass_tort_untouched=%s",
        result.complaints_deleted,
        result.orphan_clusters_deleted,
        result.clusters_recalculated,
        result.mass_tort_untouched,
    )
    return result
