"""Check CourtListener for class action filings against tracked clusters.

Phase 3a of the legal-signals layer (see docs/SIGNAL_PLAN_AND_GOALS.md).

For every WATCH+ cluster (score >= 50), query CourtListener's RECAP search
for matching federal product-liability dockets. If a match exists, populate
`class_action_filed = TRUE` along with audit columns (case name, court,
filing date, URL). The score will drop by 30 the next time the cluster is
rescored, deduplicating already-lawyered cases off the dashboard.

Usage:
    railway ssh
    python scripts/check_filings.py                # all WATCH+ clusters
    python scripts/check_filings.py --min-score 70 # only HOT+
    python scripts/check_filings.py --recheck-days 30  # refresh stale checks
    python scripts/check_filings.py --dry-run      # log only, no DB writes

Requires `COURTLISTENER_API_TOKEN` env var for the higher-rate API; without
it the script falls back to the unauthenticated public API (rate-limited to
~5K requests/day, fine for one full run on the current cluster fleet).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

# Ensure the project's `src/` is importable when this script runs directly.
sys.path.insert(0, str((__import__("pathlib").Path(__file__).resolve().parent.parent / "src")))

from signalwarn.courtlistener import (  # noqa: E402
    CourtListenerClient,
    build_query,
    find_class_action,
)
from signalwarn.db import connection  # noqa: E402
from signalwarn.historical import recalculate_cluster  # noqa: E402

log = logging.getLogger("check_filings")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-score", type=int, default=50,
                        help="Only check clusters scoring at least this (default 50, WATCH+).")
    parser.add_argument("--recheck-days", type=int, default=None,
                        help="Re-check clusters whose class_action_checked_at is older "
                             "than this many days. Default: skip already-checked.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log matches but don't write to the DB.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap on number of clusters to check (testing).")
    parser.add_argument("--matched-only", action="store_true",
                        help="Only re-check clusters that already have "
                             "class_action_filed=TRUE. Useful for backfilling "
                             "newly-added columns (e.g. status) without burning "
                             "API quota on the full HOT+ band.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    # Build the WHERE clause for which clusters to check.
    where_clauses = ["score >= %(min_score)s", "classification != 'NOISE'"]
    params: dict = {"min_score": args.min_score}
    if args.matched_only:
        # Re-check existing matches only — a cheap way to backfill new
        # columns onto rows that already have class_action_filed=TRUE.
        where_clauses.append("class_action_filed = TRUE")
    elif args.recheck_days is None:
        where_clauses.append("class_action_checked_at IS NULL")
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.recheck_days)
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
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        clusters = cur.fetchall()

    if not clusters:
        log.info("Nothing to check — all clusters meeting the criteria are up to date.")
        return 0

    log.info("Checking %s clusters against CourtListener…", len(clusters))
    if args.dry_run:
        log.info("DRY RUN — no DB writes will be made.")

    found = 0
    skipped = 0
    errors = 0
    start = time.time()

    with CourtListenerClient() as client:
        for i, c in enumerate(clusters, 1):
            if i % 50 == 0:
                rate = i / (time.time() - start)
                eta = (len(clusters) - i) / rate if rate > 0 else 0
                log.info(
                    "  …%s/%s checked (%s matched, %s skipped, %s errors) — ETA %.0fs",
                    i, len(clusters), found, skipped, errors, eta,
                )
            q = build_query(c["make"], c["model"], c["component"])
            if q is None:
                # Component too generic (e.g. "OTHER") — skip rather than waste a request.
                skipped += 1
                _mark_checked(c["id"], filing=None, dry_run=args.dry_run)
                continue
            try:
                filing = find_class_action(client, c["make"], c["model"], c["component"])
            except Exception as e:  # noqa: BLE001
                log.warning("error on cluster %s (%s %s %s): %s",
                            c["id"], c["make"], c["model"], c["component"], e)
                errors += 1
                continue
            if filing:
                found += 1
                tag = filing.status.upper()
                if filing.status == "terminated":
                    tag += f" {filing.date_terminated}"
                log.info(
                    "  match [%s]: %s %s %s [%s] → %s (%s, filed %s)",
                    tag, c["make"], c["model"], c["component"], c["classification"],
                    filing.case_name, filing.court, filing.date_filed,
                )
            _mark_checked(c["id"], filing=filing, dry_run=args.dry_run)

    elapsed = time.time() - start
    log.info(
        "Done. checked=%s matched=%s skipped=%s errors=%s in %.1fs",
        len(clusters), found, skipped, errors, elapsed,
    )

    if found and not args.dry_run:
        # Re-score just the matched clusters so the -30 penalty applies now,
        # rather than waiting for the next ingestion.
        log.info("Rescoring %s matched clusters to apply the -30 penalty…", found)
        with connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM clusters WHERE class_action_filed = TRUE "
                "AND class_action_checked_at >= %s",
                (datetime.now(timezone.utc) - timedelta(hours=1),),
            )
            ids = [r["id"] for r in cur.fetchall()]
            cur.close()
            for cid in ids:
                recalculate_cluster(conn, cid)
        log.info("Rescored %s clusters.", len(ids))

    return 0


def _mark_checked(cluster_id: int, *, filing, dry_run: bool) -> None:
    """Record the check in the DB. Sets class_action_filed if a match was found,
    plus class_action_status ('pending' or 'terminated') and termination date.
    Terminated cases are filtered out of the dashboard by the read query —
    see web/queries.py::list_clusters."""
    if dry_run:
        return
    now = datetime.now(timezone.utc)
    with connection() as conn, conn.cursor() as cur:
        if filing is None:
            cur.execute(
                """
                UPDATE clusters
                   SET class_action_filed = FALSE,
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
                       class_action_url = %s,
                       class_action_case_name = %s,
                       class_action_court = %s,
                       class_action_filed_date = %s,
                       class_action_status = %s,
                       class_action_terminated_date = %s,
                       class_action_checked_at = %s
                 WHERE id = %s
                """,
                (filing.url, filing.case_name, filing.court,
                 filing.date_filed, filing.status, filing.date_terminated,
                 now, cluster_id),
            )


if __name__ == "__main__":
    raise SystemExit(main())
