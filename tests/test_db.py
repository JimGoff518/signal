"""Tests for db helpers — focus on the URL normalization that prevents
SQLAlchemy from trying to import psycopg2 AND keeps raw psycopg.connect happy."""
from __future__ import annotations

import pytest

from signalwarn.db import _psycopg_url, _sqlalchemy_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Vanilla postgresql:// gets rewritten to use psycopg v3.
        (
            "postgresql://user:pass@localhost:5432/db",
            "postgresql+psycopg://user:pass@localhost:5432/db",
        ),
        # Heroku-style postgres:// also rewrites.
        (
            "postgres://user:pass@h.example.com:5432/db",
            "postgresql+psycopg://user:pass@h.example.com:5432/db",
        ),
        # Already-explicit psycopg URL passes through unchanged.
        (
            "postgresql+psycopg://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
        # Different drivers (psycopg2, asyncpg) are left alone — caller's choice.
        (
            "postgresql+psycopg2://user:pass@host/db",
            "postgresql+psycopg2://user:pass@host/db",
        ),
        (
            "postgresql+asyncpg://user:pass@host/db",
            "postgresql+asyncpg://user:pass@host/db",
        ),
    ],
)
def test_sqlalchemy_url_normalization(raw: str, expected: str):
    assert _sqlalchemy_url(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # SQLAlchemy-style URL gets stripped back to vanilla for psycopg.connect.
        (
            "postgresql+psycopg://user:pass@host/db",
            "postgresql://user:pass@host/db",
        ),
        (
            "postgresql+psycopg2://user:pass@host/db",
            "postgresql://user:pass@host/db",
        ),
        (
            "postgresql+asyncpg://user:pass@host/db",
            "postgresql://user:pass@host/db",
        ),
        # Vanilla URL passes through unchanged.
        (
            "postgresql://user:pass@host/db",
            "postgresql://user:pass@host/db",
        ),
        # Heroku-style passes through (psycopg accepts both).
        (
            "postgres://user:pass@host/db",
            "postgres://user:pass@host/db",
        ),
    ],
)
def test_psycopg_url_normalization(raw: str, expected: str):
    assert _psycopg_url(raw) == expected
