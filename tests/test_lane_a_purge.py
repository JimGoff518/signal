"""Lane A pre-2026 filed-date gate + hard purge scope (Mass Tort untouched)."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost:5432/x")

from signalwarn.lane_a_window import (  # noqa: E402
    LANE_A_MIN_FILED_DATE,
    LANE_A_PRE_WINDOW_SQL,
    is_eligible_lane_a_filed_date,
    purge_pre_window_sql,
)
from signalwarn import migrations as migrations_mod  # noqa: E402
from signalwarn import purge_lane_a as purge_mod  # noqa: E402
from signalwarn.historical import EARLIEST_FILED_DATE  # noqa: E402
from signalwarn import ingestion as ingestion_mod  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "filed,expected",
    [
        (None, False),
        (date(2025, 12, 31), False),
        (date(2026, 1, 1), True),
        (date(2026, 6, 15), True),
        (date(2015, 1, 1), False),
    ],
)
def test_is_eligible_lane_a_filed_date(filed, expected):
    assert is_eligible_lane_a_filed_date(filed) is expected


def test_lane_a_min_filed_date_is_2026_01_01():
    assert LANE_A_MIN_FILED_DATE == date(2026, 1, 1)
    assert EARLIEST_FILED_DATE == LANE_A_MIN_FILED_DATE


def test_purge_sql_steps_lane_a_only():
    steps = purge_pre_window_sql()
    assert [label for label, _ in steps] == [
        "delete_pre_2026_complaints",
        "delete_orphan_clusters",
    ]
    joined = "\n".join(sql for _, sql in steps).lower()
    assert "complaints" in joined
    assert "clusters" in joined
    for banned in purge_mod.MASS_TORT_TABLES:
        assert banned not in joined
    # Must key off filed date, not model year.
    assert "date_complaint_filed" in joined
    assert "model_year" not in joined


def test_purge_predicate_uses_filed_date_not_incident():
    assert "date_complaint_filed" in LANE_A_PRE_WINDOW_SQL
    assert "date_of_incident" not in LANE_A_PRE_WINDOW_SQL


def test_migration_003_sql_lane_a_only_and_idempotent_shape():
    path = ROOT / "migrations" / "003_purge_pre_2026_lane_a.sql"
    text = path.read_text()
    lowered = text.lower()
    assert "date_complaint_filed" in lowered
    assert "2026-01-01" in text
    assert "delete from complaints" in lowered
    assert "delete from clusters" in lowered
    # Executable DML must never target Lane B (comments may mention the lock).
    executable = "\n".join(
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ).lower()
    assert "mass_tort" not in executable
    assert "mdl_events" not in executable
    assert "not in" in lowered or "pending" in lowered  # documents non-PENDING


def test_purge_not_in_pending_migrations():
    """Destructive purge must never auto-run on FastAPI startup."""
    for desc, sql in migrations_mod.PENDING:
        lowered = (desc + "\n" + sql).lower()
        assert "delete from complaints" not in lowered
        assert "purge_pre_2026" not in lowered
        assert "orphan_clusters" not in lowered


def test_ingestion_module_wires_filed_date_gate():
    src = Path(ingestion_mod.__file__).read_text()
    assert "is_eligible_lane_a_filed_date" in src
    assert "date_complaint_filed" in src


def test_historical_module_wires_filed_date_gate():
    from signalwarn import historical as historical_mod

    src = Path(historical_mod.__file__).read_text()
    assert "is_eligible_lane_a_filed_date" in src
    assert "EARLIEST_YEAR" not in src  # old 2015 floor removed
    assert "EARLIEST_FILED_DATE" in src


def test_purge_allow_list_excludes_mass_tort():
    assert purge_mod.MASS_TORT_TABLES.isdisjoint(purge_mod.LANE_A_PURGE_TABLES)
    assert "mass_tort_matters" in purge_mod.MASS_TORT_TABLES
    assert "mdl_events" in purge_mod.MASS_TORT_TABLES
    assert "complaints" in purge_mod.LANE_A_PURGE_TABLES


def test_purge_result_mass_tort_untouched_property():
    ok = purge_mod.PurgeResult(
        dry_run=False,
        mass_tort_matters_before=13,
        mass_tort_matters_after=13,
    )
    assert ok.mass_tort_untouched is True
    bad = purge_mod.PurgeResult(
        dry_run=False,
        mass_tort_matters_before=13,
        mass_tort_matters_after=12,
    )
    assert bad.mass_tort_untouched is False


def test_ingest_skips_pre_2026_before_insert(monkeypatch):
    """Daily ingest must skip pre-2026 filings without attempting INSERT."""
    from signalwarn.nhtsa import Complaint

    pre = Complaint(
        odi_number="PRE2025",
        manufacturer="FORD",
        make="FORD",
        model="F-150",
        model_year=2020,
        component_raw="ENGINE",
        date_of_incident=date(2025, 6, 1),
        date_complaint_filed=date(2025, 6, 15),
        vin=None,
        crash=False,
        fire=False,
        injuries=0,
        deaths=0,
        description="old",
        state="TX",
    )
    post = Complaint(
        odi_number="POST2026",
        manufacturer="FORD",
        make="FORD",
        model="F-150",
        model_year=2020,
        component_raw="ENGINE",
        date_of_incident=date(2026, 2, 1),
        date_complaint_filed=date(2026, 2, 10),
        vin=None,
        crash=False,
        fire=False,
        injuries=0,
        deaths=0,
        description="new",
        state="TX",
    )

    insert_calls: list[str] = []

    def fake_insert(conn, complaint):
        insert_calls.append(complaint.odi_number)
        return 101 if complaint.odi_number == "POST2026" else None

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def complaints_filed_since(self, make, model, year, since):
            if (make, model, year) == ("FORD", "F-150", 2020):
                return [pre, post]
            return []

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            self._row = {"id": 1}

        def fetchone(self):
            return getattr(self, "_row", {"id": 1})

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

    from contextlib import contextmanager

    @contextmanager
    def fake_connection():
        yield _Conn()

    monkeypatch.setattr(ingestion_mod, "NHTSAClient", FakeClient)
    monkeypatch.setattr(ingestion_mod, "connection", fake_connection)
    monkeypatch.setattr(ingestion_mod, "_insert_complaint", fake_insert)
    monkeypatch.setattr(ingestion_mod, "tracked_vehicle_combos", lambda: [("FORD", "F-150", 2020)])
    monkeypatch.setattr(
        ingestion_mod,
        "upsert_clusters_for_complaint",
        lambda *a, **k: [1],
    )
    monkeypatch.setattr(ingestion_mod, "recalculate_cluster", lambda *a, **k: None)

    result = ingestion_mod.run_daily_ingestion(lookback_days=30)
    assert insert_calls == ["POST2026"]
    assert result.ingested == 1
    assert result.skipped >= 1  # pre-2026 skipped (plus any duplicates)
