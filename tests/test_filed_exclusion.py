"""Clusters with a filed class action (pending or terminated) are excluded from
every surface: dashboard, signal counts, memo generation, digest, death alerts."""
from __future__ import annotations

from signalwarn import alerts, viability
from tests._fakes import FakeConn, fake_connection
from web import queries

FILED_OFF = queries.EXCLUDE_FILED_SQL


def test_signal_counts_still_count_filed_clusters_for_audit_link(monkeypatch):
    # The dashboard slice excludes filed clusters, but the "N class action" link
    # in the signals strip must still report how many exist in that slice.
    conn = FakeConn([{"clusters": 3, "recall": 1, "probe": 0, "memo": 1}, {"filed": 2}])
    monkeypatch.setattr(queries, "connection", fake_connection(conn))

    out = queries.signal_counts_in_view(make="FORD")

    assert out["filed"] == 2
    main_sql = conn.cur.calls[0][0]
    filed_sql = conn.cur.calls[1][0]
    assert FILED_OFF in main_sql
    assert "c.class_action_filed = TRUE" in filed_sql and FILED_OFF not in filed_sql


def test_memo_candidates_skip_filed_clusters(monkeypatch):
    conn = FakeConn([[{"id": 4}, {"id": 9}]])
    monkeypatch.setattr(viability, "connection", fake_connection(conn))

    assert viability.memo_candidate_ids() == [4, 9]
    sql = conn.cur.calls[0][0]
    assert "score >= " in sql and FILED_OFF in sql


def test_daily_digest_skips_filed_clusters(monkeypatch):
    conn = FakeConn([[]])
    monkeypatch.setattr(alerts, "connection", fake_connection(conn))
    monkeypatch.setattr(alerts, "_send", lambda *a, **k: None)

    alerts.send_daily_digest()

    assert FILED_OFF in conn.cur.calls[0][0]


def test_death_alerts_skip_filed_clusters(monkeypatch):
    conn = FakeConn([[]])
    monkeypatch.setattr(alerts, "connection", fake_connection(conn))
    monkeypatch.setattr(alerts, "_send", lambda *a, **k: None)

    alerts.send_death_alerts()

    assert FILED_OFF in conn.cur.calls[0][0]
