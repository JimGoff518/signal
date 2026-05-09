"""One-shot CLI to recalculate every cluster's score from raw complaint data.

Useful when the scoring formula changes (weights rebalanced) and you need every
cluster to pick up the new score *now* rather than waiting for each cluster to
be incidentally touched by a new complaint in the daily ingestion window.

Run from inside the Railway container (the prod DB hostname doesn't resolve
from a developer laptop):

    railway ssh
    python scripts/rescore_all.py

Idempotent — safe to re-run. Doesn't fetch from NHTSA or send any alerts; it
only touches the `clusters` table.
"""
from __future__ import annotations

import logging
import sys
import time

# Ensure the project's `src/` is importable when this script runs directly.
sys.path.insert(0, str((__import__("pathlib").Path(__file__).resolve().parent.parent / "src")))

from signalwarn.historical import rescore_all_clusters  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("rescore_all")
    start = time.time()
    log.info("Rescoring all clusters with the current scoring formula…")
    n = rescore_all_clusters()
    elapsed = time.time() - start
    log.info("Done. %s clusters rescored in %.1fs.", n, elapsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
