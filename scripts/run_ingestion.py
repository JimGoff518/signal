"""Daily ingestion CLI.

Pull new NHTSA complaints, store them, recluster, rescore, generate viability
memos for any cluster newly at WATCH+, and send the daily digest + death alerts.

Schedule via Railway cron (02:00 CT) for production.

    python scripts/run_ingestion.py
"""
from __future__ import annotations

import logging
import sys

import click

# Ensure the project's `src/` is importable when this script runs directly.
sys.path.insert(0, str((__import__("pathlib").Path(__file__).resolve().parent.parent / "src")))

from signalwarn.alerts import send_daily_digest, send_death_alerts  # noqa: E402
from signalwarn.config import settings  # noqa: E402
from signalwarn.db import connection  # noqa: E402
from signalwarn.ingestion import run_daily_ingestion  # noqa: E402
from signalwarn.viability import regenerate_memo_if_needed  # noqa: E402


@click.command()
@click.option("--lookback-days", type=int, default=None, help="Override NHTSA_LOOKBACK_DAYS.")
@click.option("--skip-memos", is_flag=True, help="Don't call Claude for viability memos.")
@click.option("--skip-emails", is_flag=True, help="Don't send digest or death alerts.")
def main(lookback_days: int | None, skip_memos: bool, skip_emails: bool) -> None:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("signal.ingest")

    result = run_daily_ingestion(lookback_days=lookback_days)
    log.info("Ingested %s, skipped %s, %s clusters touched", result.ingested, result.skipped, result.clusters_touched)

    if not skip_memos and settings.anthropic_api_key:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM clusters WHERE score >= 50")
            cluster_ids = [r["id"] for r in cur.fetchall()]
        for cid in cluster_ids:
            try:
                regenerate_memo_if_needed(cid)
            except Exception as e:  # noqa: BLE001
                log.warning("memo for cluster %s failed: %s", cid, e)

    if not skip_emails:
        try:
            send_death_alerts()
            send_daily_digest()
        except Exception as e:  # noqa: BLE001
            log.warning("alert send failed: %s", e)


if __name__ == "__main__":
    main()
