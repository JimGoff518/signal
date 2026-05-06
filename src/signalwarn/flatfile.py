"""Streaming parsers for NHTSA flat-file dumps.

NHTSA publishes three tab-delimited flat files:
  FLAT_CMPL.txt  — consumer complaints (1995–present, ~700MB+)
  FLAT_RCL_POST_2010.txt — recalls (305MB)
  FLAT_INV.txt   — investigations (389MB)

These are too large for csv.reader's default behaviour (descriptions break the
field-size limit) and contain Latin-1 bytes. We stream them line-by-line and
yield typed records.

Field layouts:
  Complaints:   https://static.nhtsa.gov/odi/ffdd/cmpl/CMPL.txt
  Recalls:      ./RCL.txt (also bundled at NHTSA)
  Investigations: https://static.nhtsa.gov/odi/ffdd/inv/INV.txt
"""
from __future__ import annotations

import csv
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import IO, Iterator

# NHTSA descriptions can be 6KB. Bump csv's field-size limit.
csv.field_size_limit(min(2**31 - 1, sys.maxsize))


def _open_flat(path: Path | str) -> IO[str]:
    """Return a text stream for either a .txt file or a .zip containing one."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(p)
        member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        return zf.open(member, "r")  # type: ignore[return-value]  # binary; see _decode below
    return p.open("rb")  # type: ignore[return-value]


def _decode_lines(stream) -> Iterator[str]:
    """Yield Latin-1 decoded lines from a binary stream."""
    for raw in stream:
        yield raw.decode("latin-1", errors="replace").rstrip("\r\n")


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw or raw == "00000000":
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def _yn(raw: str) -> bool:
    return (raw or "").strip().upper() == "Y"


def _int(raw: str) -> int:
    raw = (raw or "").strip()
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


# ─── Complaints ─────────────────────────────────────────────────────────
# CMPL field layout (1-indexed → 0-indexed for slicing):
#   1 CMPLID, 2 ODINO, 3 MFR_NAME, 4 MAKETXT, 5 MODELTXT, 6 YEARTXT,
#   7 CRASH, 8 FAILDATE, 9 FIRE, 10 INJURED, 11 DEATHS, 12 COMPDESC,
#   13 CITY, 14 STATE, 15 VIN, 16 DATEA, 17 LDATE, 18 MILES, 19 OCCURENCES,
#   20 CDESCR (description, up to 2048 chars), ... (49 fields total).

@dataclass(frozen=True)
class FlatComplaint:
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


def iter_complaints(path: Path | str) -> Iterator[FlatComplaint]:
    """Yield FlatComplaint records from FLAT_CMPL.zip or .txt."""
    with _open_flat(path) as stream:
        for line in _decode_lines(stream):
            f = line.split("\t")
            if len(f) < 20:
                continue
            year = _int(f[5])
            if year == 9999 or year == 0:
                continue
            yield FlatComplaint(
                odi_number=f[1].strip(),
                manufacturer=(f[2] or None),
                make=f[3].strip().upper(),
                model=f[4].strip().upper(),
                model_year=year,
                component_raw=(f[11] or None),
                date_of_incident=_parse_date(f[7]),
                date_complaint_filed=_parse_date(f[16]),
                vin=(f[14] or None),
                crash=_yn(f[6]),
                fire=_yn(f[8]),
                injuries=_int(f[9]),
                deaths=_int(f[10]),
                description=(f[19] or None) if len(f) > 19 else None,
                state=(f[13] or None),
            )


# ─── Recalls ────────────────────────────────────────────────────────────
# RCL field layout (see RCL.txt): 1 RECORD_ID, 2 CAMPNO, 3 MAKETXT, 4 MODELTXT,
#   5 YEARTXT (or 9999 = unknown/all), 6 MFGCAMPNO, 7 COMPNAME, ...

@dataclass(frozen=True)
class FlatRecall:
    record_id: str
    campaign_no: str
    make: str
    models: list[str]
    model_year: int | None  # None if 9999 (all years)
    component_raw: str | None


def iter_recalls(path: Path | str) -> Iterator[FlatRecall]:
    with _open_flat(path) as stream:
        for line in _decode_lines(stream):
            f = line.split("\t")
            if len(f) < 7:
                continue
            year = _int(f[4])
            yield FlatRecall(
                record_id=f[0].strip(),
                campaign_no=f[1].strip(),
                make=f[2].strip().upper(),
                models=[m.strip().upper() for m in (f[3] or "").split(",") if m.strip()],
                model_year=None if year in (0, 9999) else year,
                component_raw=(f[6] or None),
            )


# ─── Investigations ─────────────────────────────────────────────────────
# INV field layout: 1 NHTSA_ACTION_NUMBER, 2 MAKETXT, 3 MODELTXT, 4 YEARTXT,
#   5 COMPNAME, 6 MFR_NAME, 7 ODATE (open), 8 CDATE (close — empty = open),
#   9 CAMPNO, 10 SUBJECT, 11 SUMMARY.

@dataclass(frozen=True)
class FlatInvestigation:
    action_number: str
    make: str
    models: list[str]
    model_year: int | None
    component_raw: str | None
    open_date: date | None
    close_date: date | None  # None = still open


def iter_investigations(path: Path | str) -> Iterator[FlatInvestigation]:
    with _open_flat(path) as stream:
        for line in _decode_lines(stream):
            f = line.split("\t")
            if len(f) < 8:
                continue
            year = _int(f[3])
            yield FlatInvestigation(
                action_number=f[0].strip(),
                make=f[1].strip().upper(),
                models=[m.strip().upper() for m in (f[2] or "").split(",") if m.strip()],
                model_year=None if year in (0, 9999) else year,
                component_raw=(f[4] or None),
                open_date=_parse_date(f[6]),
                close_date=_parse_date(f[7]),
            )


def is_investigation_open(inv: FlatInvestigation) -> bool:
    return inv.close_date is None
