"""Tests for NHTSA flat-file parsers."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from signalwarn.flatfile import (
    iter_complaints,
    iter_investigations,
    iter_recalls,
    is_investigation_open,
)


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    p = tmp_path / name
    p.write_bytes(("\n".join(lines)).encode("latin-1"))
    return p


# ─── Complaints ─────────────────────────────────────────────────────────

def _cmpl_row(overrides: dict[int, str] | None = None) -> str:
    """Build a 49-field FLAT_CMPL line. Override only what each test cares about."""
    row = [""] * 49
    defaults: dict[int, str] = {
        0: "1",
        1: "10001",            # ODINO
        2: "FORD MOTOR CO",    # MFR_NAME
        3: "FORD",             # MAKETXT
        4: "F-150",            # MODELTXT
        5: "2023",             # YEARTXT
        6: "Y",                # CRASH
        7: "20240101",         # FAILDATE
        8: "N",                # FIRE
        9: "1",                # INJURED
        10: "0",               # DEATHS
        11: "POWER TRAIN",     # COMPDESC
        12: "DALLAS",          # CITY
        13: "TX",              # STATE
        14: "1FTFW1ET5DFA",    # VIN
        15: "20240115",        # DATEA
        16: "20240115",        # LDATE
        19: "Truck shudders at highway speed.",  # CDESCR
    }
    if overrides:
        defaults.update(overrides)
    for i, v in defaults.items():
        row[i] = str(v)
    return "\t".join(row)


def test_iter_complaints_parses_a_row(tmp_path):
    f = _write(tmp_path, "FLAT_CMPL.txt", [_cmpl_row()])
    [c] = list(iter_complaints(f))
    assert c.odi_number == "10001"
    assert c.make == "FORD"
    assert c.model == "F-150"
    assert c.model_year == 2023
    assert c.crash is True
    assert c.fire is False
    assert c.injuries == 1
    assert c.deaths == 0
    assert c.date_complaint_filed == date(2024, 1, 15)
    assert c.state == "TX"


def test_iter_complaints_skips_year_9999(tmp_path):
    f = _write(tmp_path, "FLAT_CMPL.txt", [_cmpl_row({5: "9999"})])
    assert list(iter_complaints(f)) == []


def test_iter_complaints_handles_missing_dates(tmp_path):
    f = _write(tmp_path, "FLAT_CMPL.txt", [_cmpl_row({16: "00000000"})])
    [c] = list(iter_complaints(f))
    assert c.date_complaint_filed is None


# ─── Recalls ────────────────────────────────────────────────────────────

def _rcl_row(overrides: dict[int, str] | None = None) -> str:
    row = [""] * 29
    defaults: dict[int, str] = {
        0: "1",
        1: "23V123000",        # CAMPNO
        2: "FORD",             # MAKETXT
        3: "F-150,F-250",      # MODELTXT (comma-separated)
        4: "2023",             # YEARTXT
        6: "POWER TRAIN",      # COMPNAME
    }
    if overrides:
        defaults.update(overrides)
    for i, v in defaults.items():
        row[i] = str(v)
    return "\t".join(row)


def test_iter_recalls_splits_comma_separated_models(tmp_path):
    f = _write(tmp_path, "FLAT_RCL.txt", [_rcl_row()])
    [r] = list(iter_recalls(f))
    assert r.models == ["F-150", "F-250"]
    assert r.model_year == 2023


def test_iter_recalls_treats_year_9999_as_all_years(tmp_path):
    f = _write(tmp_path, "FLAT_RCL.txt", [_rcl_row({4: "9999"})])
    [r] = list(iter_recalls(f))
    assert r.model_year is None


# ─── Investigations ─────────────────────────────────────────────────────

def _inv_row(overrides: dict[int, str] | None = None) -> str:
    row = [""] * 11
    defaults: dict[int, str] = {
        0: "PE23001",          # ACTION_NUMBER
        1: "NISSAN",
        2: "ROGUE",
        3: "2023",
        4: "ENGINE AND ENGINE COOLING",
        6: "20231215",         # ODATE
        7: "",                 # CDATE — empty = open
    }
    if overrides:
        defaults.update(overrides)
    for i, v in defaults.items():
        row[i] = str(v)
    return "\t".join(row)


def test_open_investigation_has_no_close_date(tmp_path):
    f = _write(tmp_path, "FLAT_INV.txt", [_inv_row()])
    [inv] = list(iter_investigations(f))
    assert inv.open_date == date(2023, 12, 15)
    assert inv.close_date is None
    assert is_investigation_open(inv) is True


def test_closed_investigation_has_close_date(tmp_path):
    f = _write(tmp_path, "FLAT_INV.txt", [_inv_row({7: "20240601"})])
    [inv] = list(iter_investigations(f))
    assert inv.close_date == date(2024, 6, 1)
    assert is_investigation_open(inv) is False
