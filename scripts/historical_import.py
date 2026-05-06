"""One-shot historical bulk import.

Loads NHTSA's flat-file dumps (complaints + recalls + investigations) into
Postgres so the dashboard launches with years of pre-clustered data.

Run this ONCE on initial deployment, then `run_ingestion.py` keeps it fresh.

    python scripts/historical_import.py

Default sources (override with --complaints, --recalls, --investigations):
    ./FLAT_CMPL.zip                   (auto-downloaded if missing)
    ./FLAT_RCL_POST_2010.zip
    ./FLAT_INV.zip
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

# Make `src/` importable when this script runs directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from signalwarn.config import settings  # noqa: E402
from signalwarn.historical import (  # noqa: E402
    apply_investigation_flags,
    apply_recall_flags,
    download_complaints_flat_file,
    import_complaints,
    rescore_all_clusters,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@click.command()
@click.option(
    "--complaints",
    type=click.Path(path_type=Path),
    default=PROJECT_ROOT / "FLAT_CMPL.zip",
    help="Path to FLAT_CMPL.zip (auto-downloaded from NHTSA if missing).",
)
@click.option(
    "--recalls",
    type=click.Path(path_type=Path),
    default=PROJECT_ROOT / "FLAT_RCL_POST_2010.zip",
    help="Path to FLAT_RCL_POST_2010.zip.",
)
@click.option(
    "--investigations",
    type=click.Path(path_type=Path),
    default=PROJECT_ROOT / "FLAT_INV.zip",
    help="Path to FLAT_INV.zip.",
)
@click.option("--skip-complaints", is_flag=True, help="Don't reload complaints.")
@click.option("--skip-recalls", is_flag=True, help="Don't apply recall flags.")
@click.option("--skip-investigations", is_flag=True, help="Don't apply investigation flags.")
def main(
    complaints: Path,
    recalls: Path,
    investigations: Path,
    skip_complaints: bool,
    skip_recalls: bool,
    skip_investigations: bool,
) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("signal.historical")

    if not skip_complaints:
        complaints_path = download_complaints_flat_file(complaints)
        ins, skipped = import_complaints(complaints_path)
        log.info("Complaints loaded: %s inserted, %s skipped", ins, skipped)
    else:
        log.info("Skipping complaints (per --skip-complaints)")

    if not skip_recalls:
        if not recalls.exists():
            log.warning("Recalls file missing: %s — skipping", recalls)
        else:
            n = apply_recall_flags(recalls)
            log.info("Recall flags set on %s clusters", n)

    if not skip_investigations:
        if not investigations.exists():
            log.warning("Investigations file missing: %s — skipping", investigations)
        else:
            n = apply_investigation_flags(investigations)
            log.info("Investigation flags set on %s clusters", n)

    log.info("Final rescore pass…")
    n = rescore_all_clusters()
    log.info("Done. %s clusters rescored. Launch the dashboard with `streamlit run src/signalwarn/app.py`.", n)


if __name__ == "__main__":
    main()
