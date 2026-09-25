"""Reusable core for the CourtListener filings check.

Extracted out of `scripts/check_filings.py` so the FastAPI admin endpoint
can call the same code (as a background task) without shelling out. The
script and the admin endpoint go through one entry point: `run_check_filings`.

Returns a dict summary so the caller can render or log the outcome.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from signalwarn.courtlistener import (
    CourtListenerClient,
    build_query,
    find_class_action,
    names_defect,
)
from signalwarn.filing_corrections import (
    correction_notes,
    same_defect_override,
    status_override,
)
from signalwarn.db import connection
from signalwarn.historical import recalculate_cluster

log = logging.getLogger(__name__)


def run_check_filings(
    *,
    min_score: int = 50,
    recheck_days: int | None = None,
    matched_only: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    """Walk the filtered cluster set, query CourtListener, persist results.

    Returns: {checked, matched, skipped, errors, elapsed_seconds}.
    """
    where_clauses = ["score >= %(min_score)s", "classification != 'NOISE'"]
    params: dict = {"min_score": min_score}
    if matched_only:
        where_clauses.append("class_action_filed = TRUE")
    elif recheck_days is None:
        where_clauses.append("class_action_checked_at IS NULL")
    else:
        cutoff = datetime.now(UTC) - timedelta(days=recheck_days)
        where_clauses.append(
            "(class_action_checked_at IS NULL OR class_action_checked_at < %(cutoff)s)"
        )
        params["cutoff"] = cutoff
    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT id, make, model, component, classification, score
          FROM clusters
         WHERE {where_sql}
         ORDER BY score DESC, complaint_count DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        clusters = list(cur.fetchall())

    summary = {"checked": 0, "matched": 0, "skipped": 0, "errors": 0,
               "elapsed_seconds": 0.0}

    if not clusters:
        log.info("Nothing to check — all clusters meeting the criteria are up to date.")
        return summary

    log.info("Checking %s clusters against CourtListener%s",
             len(clusters), " (DRY RUN)" if dry_run else "…")

    matched = 0
    skipped = 0
    errors = 0
    start = time.time()
    start_ts = datetime.now(UTC)

    with CourtListenerClient() as client:
        for i, c in enumerate(clusters, 1):
            if i % 50 == 0:
                rate = i / (time.time() - start)
                eta = (len(clusters) - i) / rate if rate > 0 else 0
                log.info(
                    "  …%s/%s checked (%s matched, %s skipped, %s errors) — ETA %.0fs",
                    i, len(clusters), matched, skipped, errors, eta,
                )
            q = build_query(c["make"], c["model"], c["component"])
            if q is None:
                skipped += 1
                _mark_checked(c["id"], filing=None, same_defect=False, status=None, dry_run=dry_run)
                continue
            try:
                filing = find_class_action(client, c["make"], c["model"], c["component"])
            except Exception as e:
                log.warning("error on cluster %s (%s %s %s): %s",
                            c["id"], c["make"], c["model"], c["component"], e)
                errors += 1
                continue
            if filing:
                override = same_defect_override(filing)
                same_defect = (
                    override if override is not None
                    else names_defect(filing, c["component"])
                )
                status = status_override(filing) or filing.status
                matched += 1
                tag = status.upper()
                if status == "terminated" and filing.date_terminated:
                    tag += f" {filing.date_terminated}"
                tag += " SAME DEFECT" if same_defect else " vehicle only"
                notes = correction_notes(filing)
                log.info(
                    "  match [%s]: %s %s %s [%s] → %s (%s, filed %s)%s",
                    tag, c["make"], c["model"], c["component"], c["classification"],
                    filing.case_name, filing.court, filing.date_filed,
                    f" — {notes[0]}" if notes else "",
                )
            else:
                same_defect = False
                status = None
            _mark_checked(
                c["id"], filing=filing, same_defect=same_defect,
                status=status, dry_run=dry_run,
            )

    elapsed = time.time() - start
    summary.update(
        checked=len(clusters), matched=matched, skipped=skipped, errors=errors,
        elapsed_seconds=elapsed,
    )

    if clusters and not dry_run:
        # Re-score every cluster this run touched so the -30 penalty lands
        # now on new matches and is lifted from clusters a re-check cleared,
        # rather than waiting for the next ingestion.
        log.info("Rescoring %s checked clusters to apply or lift the -30 penalty…",
                 len(clusters))
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM clusters WHERE class_action_checked_at >= %s",
                    (start_ts,),
                )
                ids = [r["id"] for r in cur.fetchall()]
            for cid in ids:
                recalculate_cluster(conn, cid)
        log.info("Rescored %s clusters.", len(ids))

    return summary


def _mark_checked(cluster_id: int, *, filing, same_defect: bool,
                  status: str | None = None, dry_run: bool = False) -> None:
    """Persist the check result. Only a same-defect match hides the cluster
    (EXCLUDE_FILED_SQL); a vehicle-level match keeps the -30 penalty.

    `status` overrides Filing.status when Scout corrections pin a value such
    as cert_denied (O'Connor 10R80). No schema change — class_action_status
    is already TEXT.
    """
    if dry_run:
        return
    now = datetime.now(UTC)
    with connection() as conn, conn.cursor() as cur:
        if filing is None:
            cur.execute(
                """
                UPDATE clusters
                   SET class_action_filed = FALSE,
                       class_action_same_defect = FALSE,
                       class_action_url = NULL,
                       class_action_case_name = NULL,
                       class_action_court = NULL,
                       class_action_filed_date = NULL,
                       class_action_status = NULL,
                       class_action_terminated_date = NULL,
                       class_action_checked_at = %s
                 WHERE id = %s
                """,
                (now, cluster_id),
            )
        else:
            cur.execute(
                """
                UPDATE clusters
                   SET class_action_filed = TRUE,
                       class_action_same_defect = %s,
                       class_action_url = %s,
                       class_action_case_name = %s,
                       class_action_court = %s,
                       class_action_filed_date = %s,
                       class_action_status = %s,
                       class_action_terminated_date = %s,
                       class_action_checked_at = %s
                 WHERE id = %s
                """,
                (same_defect, filing.url, filing.case_name, filing.court,
                 filing.date_filed, status or filing.status, filing.date_terminated,
                 now, cluster_id),
            )
