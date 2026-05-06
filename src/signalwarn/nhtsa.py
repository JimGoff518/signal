"""NHTSA public complaint API client.

Endpoints documented at https://www.nhtsa.gov/nhtsa-datasets-and-apis.
The API is unauthenticated; we are still polite about request rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

import httpx

BASE_URL = "https://api.nhtsa.gov"
TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


@dataclass(frozen=True)
class Complaint:
    odi_number: str
    manufacturer: str | None
    make: str
    model: str
    model_year: int
    component_raw: str | None
    date_of_incident: date | None
    date_complaint_filed: date | None
    vin: str | None
    crash: bool
    fire: bool
    injuries: int
    deaths: int
    description: str | None
    state: str | None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = str(raw).strip()
    # NHTSA returns ISO datetimes ("2024-09-15T00:00:00.000Z") on the JSON API
    # and YYYYMMDD strings in the flat-file dump. Handle both.
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _to_int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"y", "yes", "true", "1"}
    return bool(v)


def _record_to_complaint(record: dict) -> Complaint | None:
    odi = record.get("odiNumber") or record.get("odiNum")
    make = record.get("make")
    model = record.get("model")
    year = _to_int(record.get("modelYear") or record.get("yearOfVehicle"))
    if not odi or not make or not model or not year:
        return None
    return Complaint(
        odi_number=str(odi),
        manufacturer=record.get("manufacturer"),
        make=str(make).upper().strip(),
        model=str(model).upper().strip(),
        model_year=year,
        component_raw=record.get("components") or record.get("component"),
        date_of_incident=_parse_date(record.get("dateOfIncident")),
        date_complaint_filed=_parse_date(record.get("dateComplaintFiled")),
        vin=record.get("vin"),
        crash=_to_bool(record.get("crash")),
        fire=_to_bool(record.get("fire")),
        injuries=_to_int(record.get("numberOfInjuries") or record.get("numberOfInjured")),
        deaths=_to_int(record.get("numberOfDeaths")),
        description=record.get("summary") or record.get("description"),
        state=(record.get("state") or record.get("consumerState") or None),
    )


class NHTSAClient:
    """Thin wrapper around the NHTSA complaint API."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=TIMEOUT)

    def __enter__(self) -> "NHTSAClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def complaints_for_vehicle(
        self, make: str, model: str, model_year: int
    ) -> list[Complaint]:
        """Return all complaints on file for a given make/model/year."""
        resp = self._client.get(
            "/complaints/complaintsByVehicle",
            params={"make": make, "model": model, "modelYear": model_year},
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        results = payload.get("results") or []
        out: list[Complaint] = []
        for record in results:
            c = _record_to_complaint(record)
            if c is not None:
                out.append(c)
        return out

    def complaints_filed_since(
        self,
        make: str,
        model: str,
        model_year: int,
        since: date,
    ) -> list[Complaint]:
        """Return complaints filed on or after `since` for the given vehicle."""
        all_complaints = self.complaints_for_vehicle(make, model, model_year)
        return [
            c
            for c in all_complaints
            if c.date_complaint_filed is not None and c.date_complaint_filed >= since
        ]

    def complaints_for_vehicles(
        self, vehicles: Iterable[tuple[str, str, int]], since: date
    ) -> list[Complaint]:
        """Pull complaints filed since `since` across many vehicles."""
        out: list[Complaint] = []
        for make, model, year in vehicles:
            out.extend(self.complaints_filed_since(make, model, year, since))
        return out
