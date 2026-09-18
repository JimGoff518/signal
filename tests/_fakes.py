"""Recording fake for psycopg connections so query-shaping code can be tested
without Postgres. `rows` are the answers fetchone()/fetchall() hand back, in
order; `calls` records every (sql, params) executed."""
from __future__ import annotations

from contextlib import contextmanager


class FakeCursor:
    def __init__(self, rows: list):
        self.rows = rows
        self.calls: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.rows.pop(0) if self.rows else []


class FakeConn:
    def __init__(self, rows: list):
        self.cur = FakeCursor(rows)

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def fake_connection(conn: FakeConn):
    """Drop-in for signalwarn.db.connection (a context manager factory)."""

    @contextmanager
    def _cm():
        yield conn

    return _cm
