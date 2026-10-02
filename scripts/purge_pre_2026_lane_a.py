"""One-shot Lane A hard purge: delete NHTSA complaints filed before 2026.

Locked decision 2026-10-01 (Jimmy exact-yes via CoS / Signal room):
  - DELETE Lane A rows with date_complaint_filed < 2026-01-01 (or NULL)
  - Stop ingest of pre-2026 filings (see signalwarn.lane_a_window)
  - Mass Tort (Lane B) completely untouched
  - Irreversible hard purge (not soft-delete / staff hide)

Usage (never against prod from a shared agent box without explicit approval):

    # Preview counts only (default)
    python scripts/purge_pre_2026_lane_a.py

    # Actually delete + rescore surviving clusters
    python scripts/purge_pre_2026_lane_a.py --execute

    # Delete without rescoring (faster; run rescore_all.py later)
    python scripts/purge_pre_2026_lane_a.py --execute --skip-rescore

SQL twin: migrations/003_purge_pre_2026_lane_a.sql
  (manual / docker-init artifact — NOT in signalwarn.migrations.PENDING,
   so app startup will never auto-purge production).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from signalwarn.lane_a_window import LANE_A_MIN_FILED_DATE  # noqa: E402
from signalwarn.purge_lane_a import run_purge  # noqa: E402


@click.command()
@click.option(
    "--execute",
    is_flag=True,
    help="Perform the DELETE. Without this flag the script only previews counts.",
)
@click.option(
    "--skip-rescore",
    is_flag=True,
    help="After delete, skip recalculate_cluster on survivors.",
)
def main(execute: bool, skip_rescore: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("signal.purge_lane_a")
    log.info(
        "Lane A purge — filed-date floor=%s (calendar DATE, no TZ conversion) "
        "dry_run=%s",
        LANE_A_MIN_FILED_DATE.isoformat(),
        not execute,
    )
    result = run_purge(dry_run=not execute, rescore=execute and not skip_rescore)
    log.info(
        "complaints_matched=%s complaints_deleted=%s "
        "orphan_clusters_matched=%s orphan_clusters_deleted=%s "
        "clusters_recalculated=%s mass_tort_before=%s mass_tort_after=%s "
        "mass_tort_untouched=%s notes=%s",
        result.complaints_matched,
        result.complaints_deleted,
        result.orphan_clusters_matched,
        result.orphan_clusters_deleted,
        result.clusters_recalculated,
        result.mass_tort_matters_before,
        result.mass_tort_matters_after,
        result.mass_tort_untouched,
        "; ".join(result.notes) or "-",
    )
    if not execute:
        log.info("Dry run only. Re-run with --execute to apply the irreversible purge.")


if __name__ == "__main__":
    main()
