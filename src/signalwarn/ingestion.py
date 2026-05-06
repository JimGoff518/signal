"""Daily ingestion pipeline.

Pulls NHTSA complaints filed in the last N days for every tracked vehicle,
inserts new complaints into Postgres, attaches them to clusters, and
recalculates affected cluster scores.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from dataclasses import dataclass

from signalwarn.clustering import recalculate_cluster, upsert_clusters_for_complaint
from signalwarn.config import settings
from signalwarn.db import connection
from signalwarn.nhtsa import Complaint, NHTSAClient
from signalwarn.normalize import normalize_component

log = logging.getLogger(__name__)


# Vehicles tracked in Phase 1. See docs/SIGNAL_TECHNICAL_SPEC.md §4.4.
TRACKED_VEHICLES: list[tuple[str, list[str]]] = [
    ("FORD", ["F-150", "F-250", "RANGER", "EXPLORER", "BRONCO", "MUSTANG"]),
    ("CHEVROLET", ["SILVERADO", "COLORADO", "TAHOE", "SUBURBAN", "EQUINOX"]),
    ("GMC", ["SIERRA", "CANYON", "YUKON"]),
    ("RAM", ["1500", "2500", "3500"]),
    ("TOYOTA", ["TACOMA", "TUNDRA", "RAV4", "CAMRY"]),
    ("HONDA", ["CR-V", "ACCORD", "CIVIC", "PILOT"]),
    ("NISSAN", ["ROGUE", "ALTIMA", "FRONTIER"]),
    ("JEEP", ["GRAND CHEROKEE", "WRANGLER", "GLADIATOR"]),
    ("TESLA", ["MODEL 3", "MODEL Y", "MODEL S", "CYBERTRUCK"]),
    ("HYUNDAI", ["TUCSON", "SANTA FE", "ELANTRA"]),
    ("KIA", ["TELLURIDE", "SORENTO", "SPORTAGE"]),
]

MODEL_YEARS = list(range(2015, 2026))  # 2015–2025 per spec §4.4


def tracked_vehicle_combos() -> list[tuple[str, str, int]]:
    """Yield every (make, model, year) tuple to monitor."""
    out: list[tuple[str, str, int]] = []
    for make, models in TRACKED_VEHICLES:
        for model in models:
            for year in MODEL_YEARS:
                out.append((make, model, year))
    return out


@dataclass
class IngestionResult:
    ingested: int = 0
    skipped: int = 0
    clusters_touched: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def _insert_complaint(conn, complaint: Complaint) -> int | None:
    """Insert a complaint. Returns the new id, or None if it already existed."""
    component = normalize_component(complaint.component_raw)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO complaints (
              odi_number, manufacturer, make, model, model_year,
              component_raw, component, date_of_incident, date_complaint_filed,
              vin, crash, fire, injuries, deaths, description, state
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (odi_number) DO NOTHING
            RETURNING id
            """,
            (
                complaint.odi_number,
                complaint.manufacturer,
                complaint.make,
                complaint.model,
                complaint.model_year,
                complaint.component_raw,
                component,
                complaint.date_of_incident,
                complaint.date_complaint_filed,
                complaint.vin,
                complaint.crash,
                complaint.fire,
                complaint.injuries,
                complaint.deaths,
                complaint.description,
                complaint.state,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def run_daily_ingestion(lookback_days: int | None = None) -> IngestionResult:
    """Pull recent complaints, store, cluster, score. Returns a summary."""
    days = lookback_days if lookback_days is not None else settings.nhtsa_lookback_days
    since = date.today() - timedelta(days=days)
    log.info("Daily ingestion starting (since=%s)", since)

    result = IngestionResult()
    touched_clusters: set[int] = set()

    with connection() as conn:
        # Open the run in the ingestion log.
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_log (status) VALUES ('RUNNING') RETURNING id"
            )
            run_id = cur.fetchone()["id"]  # type: ignore[index]
        conn.commit()

        try:
            with NHTSAClient() as client:
                for make, model, year in tracked_vehicle_combos():
                    try:
                        complaints = client.complaints_filed_since(make, model, year, since)
                    except Exception as e:  # noqa: BLE001
                        msg = f"{make} {model} {year}: {e}"
                        log.warning(msg)
                        result.errors.append(msg)
                        continue

                    for complaint in complaints:
                        component = normalize_component(complaint.component_raw)
                        new_id = _insert_complaint(conn, complaint)
                        if new_id is None:
                            result.skipped += 1
                            continue
                        result.ingested += 1
                        cluster_ids = upsert_clusters_for_complaint(
                            conn,
                            new_id,
                            complaint.make,
                            complaint.model,
                            complaint.model_year,
                            component,
                        )
                        touched_clusters.update(cluster_ids)
                    conn.commit()

            for cid in touched_clusters:
                recalculate_cluster(conn, cid)
            result.clusters_touched = len(touched_clusters)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ingestion_log
                       SET complaints_ingested = %s,
                           complaints_skipped  = %s,
                           clusters_touched    = %s,
                           errors              = %s,
                           status              = 'OK'
                     WHERE id = %s
                    """,
                    (
                        result.ingested,
                        result.skipped,
                        result.clusters_touched,
                        "\n".join(result.errors) or None,
                        run_id,
                    ),
                )
        except Exception as exc:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_log SET status = 'FAILED', errors = %s WHERE id = %s",
                    (str(exc), run_id),
                )
            raise

    log.info(
        "Daily ingestion complete: ingested=%s skipped=%s clusters_touched=%s errors=%s",
        result.ingested,
        result.skipped,
        result.clusters_touched,
        len(result.errors),
    )
    return result
