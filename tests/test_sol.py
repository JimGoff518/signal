"""Statute-of-limitations rules: which complaints still count as live claims."""
from __future__ import annotations

from datetime import date

from signalwarn import migrations
from signalwarn.clustering import LIVE_COMPLAINT_SQL, sol_floor
from tests._fakes import FakeConn as _FakeConn


def test_sol_floor_subtracts_whole_years():
    assert sol_floor(date(2026, 9, 18), 4) == date(2022, 9, 18)


def test_sol_floor_handles_leap_day():
    assert sol_floor(date(2028, 2, 29), 1) == date(2027, 2, 28)


def test_live_complaint_predicate_prefers_incident_date_and_keeps_undated():
    # Incident date wins; NHTSA filing date is the fallback; no dates at all = live.
    accrual = "COALESCE(c.date_of_incident, c.date_complaint_filed) >= %(sol_floor)s"
    assert accrual in LIVE_COMPLAINT_SQL
    assert "c.date_of_incident IS NULL AND c.date_complaint_filed IS NULL" in LIVE_COMPLAINT_SQL


def test_migration_adds_time_barred_count():
    assert any("time_barred_count" in sql for _, sql in migrations.PENDING)


# ── recalculate_cluster with a recording fake connection (no Postgres) ──────


def _agg(**over):
    base = dict(
        complaint_count=3, injury_count=0, death_count=0, crash_count=0,
        fire_count=0, velocity_7d=0, velocity_30d=0,
        first_complaint_date=None, last_complaint_date=None,
        distinct_years=1, time_barred_count=2,
    )
    base.update(over)
    return base


_META = dict(model_year=2019, nhtsa_investigation_open=False, recall_issued=False,
             class_action_filed=False)


def test_recalculate_counts_only_live_complaints():
    from signalwarn.clustering import recalculate_cluster

    conn = _FakeConn([_agg(), dict(_META), {"id": 1}])
    recalculate_cluster(conn, 1)

    agg_sql, agg_params = conn.cur.calls[0]
    assert LIVE_COMPLAINT_SQL.split(" >= ")[0] in agg_sql   # aggregates gated on live claims
    assert "time_barred_count" in agg_sql
    assert agg_params["sol_floor"] == sol_floor(date.today(), 4)

    update_sql, update_params = conn.cur.calls[2]
    assert "time_barred_count" in update_sql
    assert update_params["time_barred_count"] == 2


def test_recalculate_zeroes_cluster_with_no_live_complaints():
    from signalwarn.clustering import recalculate_cluster

    conn = _FakeConn([_agg(complaint_count=0, time_barred_count=5), dict(_META), {"id": 1}])
    recalculate_cluster(conn, 1)

    update_sql, update_params = conn.cur.calls[-1]
    assert update_sql.lstrip().startswith("UPDATE clusters")
    assert update_params["complaint_count"] == 0
    assert update_params["score"] == 0
    assert update_params["classification"] == "NOISE"
    assert update_params["time_barred_count"] == 5
