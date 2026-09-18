"""EWR Death & Injury export parsing and cluster roll-up (no Postgres)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from signalwarn import ewr
from tests._fakes import FakeConn, fake_connection

FIXTURE = Path(__file__).parent / "fixtures" / "ewr_di_sample.txt"


def test_parse_header_and_records():
    meta, records = ewr.parse_ewr_file(FIXTURE.read_text(encoding="utf-8"))
    assert meta.manufacturer == "Ford Motor Company"
    assert meta.period == "2025Q4"
    assert meta.category == "LIGHT VEHICLES"
    assert meta.total_records == 8
    assert len(records) == 8
    by_seq = {r.sequence_id: r for r in records}

    bronco = by_seq[6]
    assert (bronco.make, bronco.model, bronco.model_year) == ("FORD", "BRONCO", 2025)
    assert bronco.incident_date == date(2025, 10, 28)
    assert (bronco.deaths, bronco.injuries) == (0, 1)
    assert bronco.state is None  # blank state stays NULL
    assert bronco.components == [
        "Power Train",
        "Engine and Cooling System",
        "Steering System",
        "Other",
    ]
    assert bronco.component == "POWER TRAIN"
    assert bronco.fire is False
    assert bronco.vin_prefix == "1FMEE0RR8SL"  # trailing '...' stripped

    explorer = by_seq[32]
    assert (explorer.deaths, explorer.injuries, explorer.state) == (1, 1, "TX")
    assert explorer.vin_prefix == "UNK"

    assert by_seq[14].incident_date is None  # blank date


def test_component_choice_skips_fire_and_unspecified():
    assert ewr.pick_component(["Fire", "Fuel System"]) == "FUEL SYSTEM"
    assert ewr.pick_component(["No System/Component Specified"]) == "OTHER"
    assert ewr.pick_component(["Service Brake System, Air"]) == "BRAKES"
    assert ewr.pick_component(["Seats", "Structure"]) == "STRUCTURE"  # Seats has no bucket
    assert ewr.pick_component([]) == "OTHER"
    _, records = ewr.parse_ewr_file(FIXTURE.read_text(encoding="utf-8"))
    fire_row = next(r for r in records if r.sequence_id == 9)
    assert fire_row.fire is True and fire_row.component == "FUEL SYSTEM"


@pytest.mark.parametrize(
    "raw, expected", [("2025, Q4", "2025Q4"), ("2026 Q1", "2026Q1"), ("2024,Q2", "2024Q2")]
)
def test_parse_period(raw, expected):
    assert ewr.parse_period(raw) == expected


def test_parse_period_rejects_garbage():
    with pytest.raises(ewr.EWRParseError):
        ewr.parse_period("last quarter")


def test_parse_rejects_non_ewr_text():
    with pytest.raises(ewr.EWRParseError):
        ewr.parse_ewr_file("hello\nworld\n")
    with pytest.raises(ewr.EWRParseError):
        ewr.parse_ewr_file(
            "SEQUENCE_ID|MAKE|MODEL|\n1|FORD|X|\n"
        )  # header present, no manufacturer


def test_import_is_idempotent_and_rolls_up(monkeypatch):
    # First 8 inserts return an id, then apply's COUNT(*) row.
    rows = [{"id": i} for i in range(1, 9)] + [{"n": 5}]
    conn = FakeConn(rows)
    monkeypatch.setattr(ewr, "connection", fake_connection(conn))

    summary = ewr.import_ewr_files([("di-202542.txt", FIXTURE.read_text(encoding="utf-8"))])
    assert summary["files"] == 1 and summary["inserted"] == 8 and summary["skipped"] == 0
    assert summary["clusters_with_incidents"] == 5
    assert summary["periods"] == ["Ford Motor Company 2025Q4 (Light Vehicles)"]
    assert summary["errors"] == 0

    sqls = [c[0] for c in conn.cur.calls]
    assert sum("INSERT INTO ewr_death_injury" in s for s in sqls) == 8
    assert all(
        "ON CONFLICT (manufacturer, period, category, sequence_id) DO NOTHING" in s
        for s in sqls
        if "INSERT INTO ewr_death_injury" in s
    )
    # roll-up: reset, per-year, all-years
    updates = [s for s in sqls if s.strip().startswith("UPDATE clusters")]
    assert len(updates) == 3
    assert "c.model_year IS NOT NULL" in updates[1] and "c.model_year IS NULL" in updates[2]

    # Same file again: every insert hits the conflict clause -> fetchone() is None -> skipped.
    conn2 = FakeConn([None] * 8 + [{"n": 5}])
    monkeypatch.setattr(ewr, "connection", fake_connection(conn2))
    again = ewr.import_ewr_files([("di-202542.txt", FIXTURE.read_text(encoding="utf-8"))])
    assert again["inserted"] == 0 and again["skipped"] == 8


def test_bad_file_is_reported_not_fatal(monkeypatch):
    conn = FakeConn([{"n": 0}])
    monkeypatch.setattr(ewr, "connection", fake_connection(conn))
    summary = ewr.import_ewr_files([("notes.txt", "not an export")])
    assert summary["files"] == 0 and summary["errors"] == [
        "notes.txt: no SEQUENCE_ID header row found — is this an EWR Death & Injury export?"
    ]
