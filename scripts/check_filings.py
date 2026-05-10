"""Check CourtListener for class action filings against tracked clusters.

Phase 3a of the legal-signals layer (see docs/SIGNAL_PLAN_AND_GOALS.md).

For every WATCH+ cluster (score >= 50), query CourtListener's RECAP search
for matching federal product-liability dockets. If a match exists, populate
`class_action_filed = TRUE` along with audit columns. The score drops by 30
on the next rescore for `pending` matches; `terminated` cases are filtered
out of the dashboard entirely (settled / dismissed / SJ for defendant = no
opportunity for a new firm).

The core loop is in signalwarn.filings_check.run_check_filings() so the
FastAPI admin endpoint can call the same code without shelling out.

Usage (CLI):
    python scripts/check_filings.py                # all WATCH+ clusters
    python scripts/check_filings.py --min-score 70 # only HOT+
    python scripts/check_filings.py --matched-only # backfill existing matches

Requires `COURTLISTENER_API_TOKEN` env var for the higher-rate API; without
it the script falls back to the unauthenticated public API (~5K req/day).
"""
from __future__ import annotations

import argparse
import logging
import sys

# Ensure the project's `src/` is importable when this script runs directly.
sys.path.insert(0, str((__import__("pathlib").Path(__file__).resolve().parent.parent / "src")))

from signalwarn.filings_check import run_check_filings  # noqa: E402

log = logging.getLogger("check_filings")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--recheck-days", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--matched-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    result = run_check_filings(
        min_score=args.min_score,
        recheck_days=args.recheck_days,
        matched_only=args.matched_only,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    log.info(
        "Done. checked=%s matched=%s skipped=%s errors=%s in %.1fs",
        result["checked"], result["matched"], result["skipped"],
        result["errors"], result["elapsed_seconds"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
