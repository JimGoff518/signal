"""Historical bulk import.

Loads NHTSA's complete complaint, recall, and investigation flat files into
Postgres so the dashboard launches with years of pre-clustered, pre-scored
data instead of an empty page.

Run once on initial deployment, then `run_ingestion.py` keeps it fresh.
"""
from __future__ import annotations

import logging
import urllib.request
from datetime import date
from pathlib import Path

from signalwarn.clustering import recalculate_cluster, upsert_clusters_for_complaint
from signalwarn.db import connection
from signalwarn.flatfile import (
    iter_complaints,
    iter_investigations,
    iter_recalls,
)
from signalwarn.ingestion import TRACKED_VEHICLES
from signalwarn.normalize import normalize_component

log = logging.getLogger(__name__)

CMPL_URL = "https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip"
RCL_URL = "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip"
INV_URL = "https://static.nhtsa.gov/odi/ffdd/inv/FLAT_INV.zip"
EARLIEST_YEAR = 2015  # spec §4.4: load 2015–present
INSERT_BATCH = 5000


def _tracked_makes_and_models() -> dict[str, set[str]]:
    """Return {make: set(models)} for the Phase 1 watch list."""
    return {make: set(models) for make, models in TRACKED_VEHICLES}


def _is_tracked(tracked: dict[str, set[str]], make: str, model: str) -> bool:
    models = tracked.get(make.upper())
    if not models:
        return False
    # Match on prefix so "F-150 SUPERCREW" still maps to "F-150".
    m_upper = model.upper()
    return any(m_upper == m or m_upper.startswith(m + " ") for m in models)


def _download_if_missing(url: str, dest: Path, label: str) -> Path:
    """Fetch `url` to `dest` unless `dest` already exists. Idempotent."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        log.info("%s already present at %s — skipping download", dest.name, dest)
        return dest
    log.info("Downloading %s → %s (%s)…", url, dest, label)
    urllib.request.urlretrieve(url, dest)  # noqa: S310 — known NHTSA URL
    log.info("Downloaded %s bytes", dest.stat().st_size)
    return dest


def download_complaints_flat_file(dest: Path) -> Path:
    """Download FLAT_CMPL.zip from NHTSA if it's not already present."""
    return _download_if_missing(CMPL_URL, dest, "a few hundred MB")


def download_recalls_flat_file(dest: Path) -> Path:
    """Download FLAT_RCL_POST_2010.zip from NHTSA if it's not already present."""
    return _download_if_missing(RCL_URL, dest, "~14 MB")


def download_investigations_flat_file(dest: Path) -> Path:
    """Download FLAT_INV.zip from NHTSA if it's not already present."""
    return _download_if_missing(INV_URL, dest, "~4 MB")


# ─── Complaints ─────────────────────────────────────────────────────────

def import_complaints(complaints_path: Path) -> tuple[int, int]:
    """Bulk-load filtered complaints. Returns (inserted, skipped)."""
    tracked = _tracked_makes_and_models()
    floor = date(EARLIEST_YEAR, 1, 1)

    inserted = skipped = 0
    batch: list[tuple] = []
    cluster_jobs: list[tuple[str, str, str, int, str]] = []

    log.info("Streaming complaints from %s", complaints_path)
    with connection() as conn:
        for c in iter_complaints(complaints_path):
            if not _is_tracked(tracked, c.make, c.model):
                skipped += 1
                continue
            if c.date_complaint_filed is None or c.date_complaint_filed < floor:
                skipped += 1
                continue
            component = normalize_component(c.component_raw)
            batch.append(
                (
                    c.odi_number, c.manufacturer, c.make, c.model, c.model_year,
                    c.component_raw, component, c.date_of_incident,
                    c.date_complaint_filed, c.vin, c.crash, c.fire,
                    c.injuries, c.deaths, c.description, c.state,
                )
            )
            cluster_jobs.append((c.odi_number, c.make, c.model, c.model_year, component))
            if len(batch) >= INSERT_BATCH:
                inserted += _flush_complaint_batch(conn, batch, cluster_jobs)
                batch.clear()
                cluster_jobs.clear()
                if inserted % 5000 == 0:
                    log.info("  …%s complaints inserted so far", inserted)

        if batch:
            inserted += _flush_complaint_batch(conn, batch, cluster_jobs)

    log.info("Complaints import complete: inserted=%s skipped=%s", inserted, skipped)
    return inserted, skipped


def _flush_complaint_batch(
    conn,
    batch: list[tuple],
    cluster_jobs: list[tuple[str, str, str, int, str]],
) -> int:
    """Insert a batch of complaints and attach each to its clusters."""
    inserted_ids: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO complaints (
              odi_number, manufacturer, make, model, model_year,
              component_raw, component, date_of_incident, date_complaint_filed,
              vin, crash, fire, injuries, deaths, description, state
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (odi_number) DO NOTHING
            """,
            batch,
        )
        odi_numbers = [row[0] for row in batch]
        cur.execute(
            "SELECT id, odi_number FROM complaints WHERE odi_number = ANY(%s)",
            (odi_numbers,),
        )
        for row in cur.fetchall():
            inserted_ids[row["odi_number"]] = row["id"]

    for odi, make, model, year, component in cluster_jobs:
        cid = inserted_ids.get(odi)
        if cid is None:
            continue
        upsert_clusters_for_complaint(conn, cid, make, model, year, component)

    conn.commit()
    return len(inserted_ids)


# ─── Recall / investigation flag matching ───────────────────────────────

def apply_recall_flags(recalls_path: Path) -> int:
    """Mark cluster.recall_issued = TRUE for every cluster matching a recall."""
    return _apply_flag(
        recalls_path,
        iter_recalls,
        column="recall_issued",
        is_open=lambda _r: True,  # all recalls count
    )


def apply_investigation_flags(inv_path: Path) -> int:
    """Mark cluster.nhtsa_investigation_open = TRUE for clusters under open NHTSA probe."""
    from signalwarn.flatfile import is_investigation_open

    return _apply_flag(
        inv_path,
        iter_investigations,
        column="nhtsa_investigation_open",
        is_open=is_investigation_open,
    )


def _apply_flag(path: Path, iterator, column: str, is_open) -> int:
    """Generic flag applier for recalls + investigations."""
    tracked = _tracked_makes_and_models()
    updated_clusters: set[int] = set()

    with connection() as conn, conn.cursor() as cur:
        for record in iterator(path):
            if not is_open(record):
                continue
            if record.make not in tracked:
                continue
            component = normalize_component(record.component_raw)
            for model in record.models:
                if not _is_tracked(tracked, record.make, model):
                    continue
                # Match per-year, all-year (NULL), AND multi-year aggregate clusters
                # for this make/model/component.
                cur.execute(
                    f"""
                    UPDATE clusters
                       SET {column} = TRUE, updated_at = NOW()
                     WHERE make = %s
                       AND model = %s
                       AND component = %s
                       AND (
                         %s::int IS NULL
                         OR model_year = %s
                         OR model_year IS NULL
                       )
                    RETURNING id
                    """,
                    (record.make, model, component, record.model_year, record.model_year),
                )
                updated_clusters.update(r["id"] for r in cur.fetchall())
        conn.commit()

    log.info("%s set on %s clusters", column, len(updated_clusters))

    with connection() as conn:
        for cid in updated_clusters:
            recalculate_cluster(conn, cid)

    return len(updated_clusters)


def rescore_all_clusters() -> int:
    """Recalculate every cluster's aggregates and score from raw complaint data."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM clusters")
        ids = [r["id"] for r in cur.fetchall()]
    log.info("Recalculating %s clusters", len(ids))
    with connection() as conn:
        for i, cid in enumerate(ids, 1):
            recalculate_cluster(conn, cid)
            if i % 500 == 0:
                log.info("  …%s/%s rescored", i, len(ids))
    return len(ids)
