"""NHTSA Early Warning Reporting (EWR) — Death & Injury records.

Under the TREAD Act every light-vehicle manufacturer must report to NHTSA,
each quarter, every death or injury claim it has received, by make, model,
model year and component. NHTSA publishes those records (PII redacted) only
through its interactive "EWR Data Search" pages — there is no bulk file or
API — so the pipeline here is: Jim exports one pipe-delimited text file per
manufacturer per quarter from that search, uploads them on /admin, and this
module parses them, stores each record once, and rolls the counts up onto
the matching clusters.

Why it matters for the class-action lens: an EWR record is the manufacturer's
own admission that it received a death or injury claim about that vehicle and
component, on a date. That is direct "manufacturer knowledge" evidence, from
the manufacturer, before any lawsuit.

File layout (as exported 2026-09):

    EWR Data - Death & Injury Records Records
          NHTSA URL: https://www.nhtsa.gov/...
    Report Created on: Sep-18-2026 09:31 AM EST
    ----------------------------------------------------------

     Manufacturer Name : Ford Motor Company
      Reporting Period : 2025, Q4
    Reporting Category : LIGHT VEHICLES
         Total Records : 80

    SEQUENCE_ID|MAKE|MODEL|MODEL_YEAR|VIN|FUEL_PROPULSION_SYSTEM|INCIDENT_DATE|DEATHS|INJURIES|STATE_OR_FOREIGN_COUNTRY|COMPONENT_A|...|COMPONENT_E|
    6|FORD|BRONCO|2025|1FMEE0RR8SL...|SIF|10/28/2025|0|1||Power Train|Engine and Cooling System|...
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from signalwarn.db import connection
from signalwarn.normalize import normalize_component

log = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "SEQUENCE_ID",
    "MAKE",
    "MODEL",
    "MODEL_YEAR",
    "VIN",
    "FUEL_PROPULSION_SYSTEM",
    "INCIDENT_DATE",
    "DEATHS",
    "INJURIES",
    "STATE_OR_FOREIGN_COUNTRY",
    "COMPONENT_A",
    "COMPONENT_B",
    "COMPONENT_C",
    "COMPONENT_D",
    "COMPONENT_E",
]

# EWR component vocabulary entries that carry no vehicle-system information.
_NON_COMPONENTS = {"", "OTHER", "NO SYSTEM/COMPONENT SPECIFIED", "FIRE"}


class EWRParseError(ValueError):
    """The uploaded text is not an EWR Death & Injury export."""


@dataclass
class EWRMeta:
    manufacturer: str
    period: str  # "2025Q4"
    category: str  # "LIGHT VEHICLES", "BUSES & MEDIUM HEAVY VEHICLES", ...
    report_created: str | None = None
    total_records: int | None = None


@dataclass
class EWRRecord:
    sequence_id: int
    make: str
    model: str
    model_year: int | None
    vin_prefix: str | None
    fuel: str | None
    incident_date: date | None
    deaths: int
    injuries: int
    state: str | None
    components: list[str] = field(default_factory=list)
    component: str = "OTHER"  # normalized bucket used for cluster matching
    fire: bool = False


def parse_period(raw: str) -> str:
    """'2025, Q4' -> '2025Q4'. Raises on anything else."""
    m = re.match(r"\s*(\d{4})\s*,?\s*Q([1-4])\s*$", raw or "", re.I)
    if not m:
        raise EWRParseError(f"unrecognised reporting period: {raw!r}")
    return f"{m.group(1)}Q{m.group(2)}"


def pick_component(components: list[str]) -> str:
    """First listed component that maps to a real bucket; else OTHER.

    Manufacturers list up to five components, most-relevant first. 'Fire' and
    'No System/Component Specified' say nothing about which system failed, so
    they are skipped in favour of a later entry ('Fire | Fuel System' ->
    FUEL SYSTEM).
    """
    for c in components:
        if c.strip().upper() in _NON_COMPONENTS:
            continue
        bucket = normalize_component(c)
        if bucket != "OTHER":
            return bucket
    return "OTHER"


def _int(v: str) -> int:
    v = (v or "").strip()
    return int(v) if v.isdigit() else 0


def _date(v: str) -> date | None:
    v = (v or "").strip()
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_ewr_file(text: str) -> tuple[EWRMeta, list[EWRRecord]]:
    """Parse one exported file into its header metadata and records."""
    lines = text.splitlines()
    header_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip().upper().startswith("SEQUENCE_ID|")), None
    )
    if header_idx is None:
        raise EWRParseError(
            "no SEQUENCE_ID header row found — is this an EWR Death & Injury export?"
        )

    meta_fields: dict[str, str] = {}
    for ln in lines[:header_idx]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            meta_fields[k.strip().lower()] = v.strip()
    manufacturer = meta_fields.get("manufacturer name") or ""
    if not manufacturer:
        raise EWRParseError("missing 'Manufacturer Name' in file header")
    meta = EWRMeta(
        manufacturer=manufacturer,
        period=parse_period(meta_fields.get("reporting period", "")),
        category=(meta_fields.get("reporting category") or "UNKNOWN").upper(),
        report_created=meta_fields.get("report created on"),
        total_records=int(meta_fields["total records"])
        if meta_fields.get("total records", "").isdigit()
        else None,
    )

    cols = [c.strip().upper() for c in lines[header_idx].strip().strip("|").split("|")]
    if cols[: len(EXPECTED_COLUMNS)] != EXPECTED_COLUMNS:
        raise EWRParseError(f"unexpected column layout: {cols[:6]}…")

    records: list[EWRRecord] = []
    for ln in lines[header_idx + 1 :]:
        if not ln.strip():
            continue
        cells = ln.rstrip("\r\n").split("|")
        if len(cells) < len(EXPECTED_COLUMNS):
            log.warning("EWR row skipped (too few fields): %r", ln[:80])
            continue
        row = dict(zip(EXPECTED_COLUMNS, cells[: len(EXPECTED_COLUMNS)], strict=True))
        components = [
            row[f"COMPONENT_{k}"].strip() for k in "ABCDE" if row[f"COMPONENT_{k}"].strip()
        ]
        year = row["MODEL_YEAR"].strip()
        records.append(
            EWRRecord(
                sequence_id=_int(row["SEQUENCE_ID"]),
                make=row["MAKE"].strip().upper(),
                model=row["MODEL"].strip().upper(),
                model_year=int(year) if year.isdigit() else None,
                vin_prefix=(row["VIN"].strip().rstrip(".") or None),
                fuel=(row["FUEL_PROPULSION_SYSTEM"].strip() or None),
                incident_date=_date(row["INCIDENT_DATE"]),
                deaths=_int(row["DEATHS"]),
                injuries=_int(row["INJURIES"]),
                state=(row["STATE_OR_FOREIGN_COUNTRY"].strip().upper() or None),
                components=components,
                component=pick_component(components),
                fire=any(c.strip().upper() == "FIRE" for c in components),
            )
        )
    return meta, records


# ─── Persistence ────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT INTO ewr_death_injury (
  manufacturer, period, category, sequence_id,
  make, model, model_year, vin_prefix, fuel, incident_date,
  deaths, injuries, state, components, component, fire, source_file
) VALUES (
  %(manufacturer)s, %(period)s, %(category)s, %(sequence_id)s,
  %(make)s, %(model)s, %(model_year)s, %(vin_prefix)s, %(fuel)s, %(incident_date)s,
  %(deaths)s, %(injuries)s, %(state)s, %(components)s, %(component)s, %(fire)s, %(source_file)s
)
ON CONFLICT (manufacturer, period, category, sequence_id) DO NOTHING
RETURNING id
"""

# Roll-up: reset, then set per-year clusters, then the ALL_YEARS aggregates.
APPLY_SQL = [
    "UPDATE clusters SET ewr_incident_count = 0, ewr_death_count = 0, ewr_injury_count = 0 "
    "WHERE ewr_incident_count <> 0 OR ewr_death_count <> 0 OR ewr_injury_count <> 0",
    """
    UPDATE clusters c
       SET ewr_incident_count = a.n, ewr_death_count = a.d, ewr_injury_count = a.i
      FROM (SELECT make, model, model_year, component,
                   COUNT(*) AS n, COALESCE(SUM(deaths), 0) AS d, COALESCE(SUM(injuries), 0) AS i
              FROM ewr_death_injury
             WHERE model_year IS NOT NULL
             GROUP BY make, model, model_year, component) a
     WHERE c.model_year IS NOT NULL
       AND c.make = a.make AND c.model = a.model
       AND c.model_year = a.model_year AND c.component = a.component
    """,
    """
    UPDATE clusters c
       SET ewr_incident_count = a.n, ewr_death_count = a.d, ewr_injury_count = a.i
      FROM (SELECT make, model, component,
                   COUNT(*) AS n, COALESCE(SUM(deaths), 0) AS d, COALESCE(SUM(injuries), 0) AS i
              FROM ewr_death_injury
             GROUP BY make, model, component) a
     WHERE c.model_year IS NULL
       AND c.make = a.make AND c.model = a.model AND c.component = a.component
    """,
]


def import_ewr_records(
    conn, meta: EWRMeta, records: list[EWRRecord], source_file: str
) -> dict[str, int]:
    """Insert records (idempotent on manufacturer+period+category+sequence)."""
    inserted = skipped = 0
    with conn.cursor() as cur:
        for r in records:
            cur.execute(
                INSERT_SQL,
                {
                    "manufacturer": meta.manufacturer,
                    "period": meta.period,
                    "category": meta.category,
                    "sequence_id": r.sequence_id,
                    "make": r.make,
                    "model": r.model,
                    "model_year": r.model_year,
                    "vin_prefix": r.vin_prefix,
                    "fuel": r.fuel,
                    "incident_date": r.incident_date,
                    "deaths": r.deaths,
                    "injuries": r.injuries,
                    "state": r.state,
                    "components": r.components,
                    "component": r.component,
                    "fire": r.fire,
                    "source_file": source_file,
                },
            )
            if cur.fetchone():
                inserted += 1
            else:
                skipped += 1
    return {"inserted": inserted, "skipped": skipped}


def apply_ewr_to_clusters(conn) -> int:
    """Recompute clusters.ewr_* from every stored record. Returns clusters touched."""
    with conn.cursor() as cur:
        for sql in APPLY_SQL:
            cur.execute(sql)
        cur.execute("SELECT COUNT(*) AS n FROM clusters WHERE ewr_incident_count > 0")
        row = cur.fetchone() or {}
    return int(row.get("n") or 0)


def import_ewr_files(files: list[tuple[str, str]]) -> dict[str, Any]:
    """Parse + store a batch of (filename, text) uploads, then refresh the
    cluster roll-ups. One bad file is reported, not fatal for the batch."""
    summary: dict[str, Any] = {
        "files": 0,
        "inserted": 0,
        "skipped": 0,
        "errors": [],
        "periods": set(),
    }
    with connection() as conn:
        for name, text in files:
            try:
                meta, records = parse_ewr_file(text)
            except EWRParseError as e:
                summary["errors"].append(f"{name}: {e}")
                continue
            counts = import_ewr_records(conn, meta, records, source_file=name)
            summary["files"] += 1
            summary["inserted"] += counts["inserted"]
            summary["skipped"] += counts["skipped"]
            summary["periods"].add(f"{meta.manufacturer} {meta.period} ({meta.category.title()})")
            log.info(
                "EWR %s: %s inserted, %s already present",
                name,
                counts["inserted"],
                counts["skipped"],
            )
        summary["clusters_with_incidents"] = apply_ewr_to_clusters(conn)
        conn.commit()
    summary["periods"] = sorted(summary["periods"])
    summary["errors"] = summary["errors"] or 0
    return summary
