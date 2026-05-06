"""Postgres connection management.

Uses a global SQLAlchemy engine + raw psycopg connections for queries.
Streamlit and CLI scripts both reuse the same engine.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from signalwarn.config import settings

_engine: Engine | None = None


def _sqlalchemy_url(raw: str) -> str:
    """Force psycopg v3 dialect. Vanilla `postgresql://` makes SQLAlchemy
    try to import psycopg2, which we don't install."""
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://"):]
    if raw.startswith("postgres://"):  # Heroku-style
        return "postgresql+psycopg://" + raw[len("postgres://"):]
    return raw


def _psycopg_url(raw: str) -> str:
    """Strip SQLAlchemy's `+driver` suffix. Raw psycopg.connect() only
    accepts `postgresql://` or `postgres://` URIs, not `postgresql+psycopg://`."""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql+asyncpg://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix):]
    return raw


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            _sqlalchemy_url(settings.database_url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection with dict-row cursors. Auto-commits on success."""
    conn = psycopg.connect(_psycopg_url(settings.database_url), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
