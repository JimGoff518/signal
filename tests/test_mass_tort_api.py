"""Lane B mass-tort API — query shaping + route auth/validation (no Postgres)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost:5432/x")

from tests._fakes import FakeConn, fake_connection
from web import mass_tort_queries as mtq
from web.mass_tort_api import HumanLabel, MatterHarvestWrite, MatterPatch, require_api_auth


def test_list_order_sql_invest_first_then_priority_then_caption():
    assert "human_label = 'INVEST'" in mtq.LIST_ORDER_SQL
    assert "priority_rank ASC NULLS LAST" in mtq.LIST_ORDER_SQL
    assert "caption ASC" in mtq.LIST_ORDER_SQL


def test_list_matters_rejects_bad_label():
    with pytest.raises(ValueError, match="invalid human_label"):
        mtq.list_matters(human_label="NOISE")


def test_list_matters_filter_and_order(monkeypatch):
    expected = [{"slug": "ai-litigation", "human_label": "INVEST"}]
    conn = FakeConn([expected])
    monkeypatch.setattr(mtq, "connection", fake_connection(conn))
    out = mtq.list_matters(human_label="INVEST")
    assert out == expected
    sql, params = conn.cur.calls[0]
    assert "WHERE human_label = %(human_label)s" in sql
    assert mtq.LIST_ORDER_SQL in sql
    assert params == {"human_label": "INVEST"}
    # Lane A tables must never appear.
    assert "clusters" not in sql and "complaints" not in sql
    assert "digests" not in sql and "ads" not in sql


def test_patch_matter_updates_label_touches_updated_at(monkeypatch):
    matter_id = uuid4()
    updated = {
        "id": matter_id,
        "slug": "galaxy-gas",
        "caption": "Galaxy Gas (N₂O)",
        "parent_slug": None,
        "human_label": "CHASE",
        "invest_score": None,
        "mdl_or_jccp_id": None,
        "court": None,
        "pending_count": None,
        "last_event_at": None,
        "last_event_type": None,
        "source_urls": [],
        "notes": "Jimmy chase",
        "priority_rank": 3,
        "updated_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }
    conn = FakeConn([updated])
    monkeypatch.setattr(mtq, "connection", fake_connection(conn))
    out = mtq.patch_matter(
        "galaxy-gas",
        {"human_label": "CHASE", "notes": "Jimmy chase"},
    )
    assert out["human_label"] == "CHASE"
    sql, params = conn.cur.calls[0]
    set_clause = sql.split("RETURNING", 1)[0]
    assert "human_label = %(human_label)s" in set_clause
    assert "notes = %(notes)s" in set_clause
    assert "updated_at = NOW()" in set_clause
    assert "invest_score" not in set_clause
    assert params["human_label"] == "CHASE"
    assert params["slug"] == "galaxy-gas"


def test_patch_matter_rejects_invest_score_and_empty():
    with pytest.raises(ValueError, match="unpatchable"):
        mtq.patch_matter("x", {"invest_score": 90})
    with pytest.raises(ValueError, match="no patch fields"):
        mtq.patch_matter("x", {})


def test_matter_patch_model_excludes_invest_score():
    body = MatterPatch(human_label=HumanLabel.WATCH, notes="n")
    dumped = body.model_dump(exclude_unset=True)
    assert "invest_score" not in dumped
    assert dumped["human_label"] is HumanLabel.WATCH


def test_require_api_auth_401_without_session():
    from fastapi import HTTPException
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/mass-tort/matters",
        "headers": [],
        "query_string": b"",
        "client": ("test", 0),
        "server": ("test", 80),
        "scheme": "http",
        "session": {},
    }
    request = Request(scope)
    with pytest.raises(HTTPException) as exc:
        require_api_auth(request)
    assert exc.value.status_code == 401


def test_api_routes_registered_and_patch_requires_auth():
    from fastapi.testclient import TestClient

    from web import app as webapp
    from web.mass_tort_api import router as mt_router

    client = TestClient(webapp.app, base_url="https://testserver", follow_redirects=False)
    # Anonymous GET/PATCH → 401 (API auth), not 303 HTML redirect.
    assert client.get("/api/mass-tort/matters").status_code == 401
    assert client.patch(
        "/api/mass-tort/matters/galaxy-gas",
        json={"human_label": "PASS"},
    ).status_code == 401

    paths = {r.path for r in mt_router.routes}
    assert "/api/mass-tort/matters" in paths or "/matters" in paths
    methods_by_path = {}
    for r in mt_router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or [])
    # Router may store paths with or without prefix depending on FastAPI version.
    matter_paths = [p for p in methods_by_path if p.endswith("/matters")]
    slug_paths = [p for p in methods_by_path if p.endswith("/matters/{slug}")]
    assert matter_paths and "GET" in methods_by_path[matter_paths[0]]
    assert slug_paths
    assert "GET" in methods_by_path[slug_paths[0]]
    assert "PATCH" in methods_by_path[slug_paths[0]]
    harvest_paths = [p for p in methods_by_path if p.endswith("/matters/{slug}/harvest")]
    assert harvest_paths
    assert "PUT" in methods_by_path[harvest_paths[0]]
    assert client.put(
        "/api/mass-tort/matters/galaxy-gas/harvest",
        json={"pending_count": 1},
    ).status_code == 401


def test_apply_harvest_write_updates_fields_not_label(monkeypatch):
    matter_id = uuid4()
    updated = {
        "id": matter_id,
        "slug": "glp1-gi",
        "caption": "GLP-1 GI / gastroparesis",
        "parent_slug": None,
        "human_label": "INVEST",
        "invest_score": None,
        "mdl_or_jccp_id": "MDL-3094",
        "court": "E.D. Pa.",
        "pending_count": 4100,
        "last_event_at": datetime.now(timezone.utc),
        "last_event_type": "other",
        "source_urls": ["https://example.com/a"],
        "notes": "WoW bump",
        "priority_rank": 6,
        "updated_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }
    conn = FakeConn([updated])
    monkeypatch.setattr(mtq, "connection", fake_connection(conn))
    out = mtq.apply_harvest_write(
        "glp1-gi",
        {
            "pending_count": 4100,
            "last_event_type": "other",
            "source_urls": ["https://example.com/a"],
            "notes": "WoW bump",
        },
    )
    assert out["pending_count"] == 4100
    assert out["human_label"] == "INVEST"
    sql, params = conn.cur.calls[0]
    set_clause = sql.split("RETURNING", 1)[0]
    assert "pending_count = %(pending_count)s" in set_clause
    assert "human_label" not in set_clause
    assert "invest_score" not in set_clause
    assert "priority_rank" not in set_clause
    assert params["slug"] == "glp1-gi"


def test_apply_harvest_rejects_label_and_score():
    with pytest.raises(ValueError, match="unharvestable"):
        mtq.apply_harvest_write("x", {"human_label": "PASS"})
    with pytest.raises(ValueError, match="unharvestable"):
        mtq.apply_harvest_write("x", {"invest_score": 50})
    with pytest.raises(ValueError, match="no harvest fields"):
        mtq.apply_harvest_write("x", {})


def test_apply_harvest_appends_event(monkeypatch):
    matter_id = uuid4()
    base = {
        "id": matter_id,
        "slug": "roblox",
        "caption": "Roblox",
        "parent_slug": None,
        "human_label": "INVEST",
        "invest_score": None,
        "mdl_or_jccp_id": "MDL-3166",
        "court": "N.D. Cal.",
        "pending_count": 182,
        "last_event_at": None,
        "last_event_type": None,
        "source_urls": [],
        "notes": None,
        "priority_rank": 4,
        "updated_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }
    synced = dict(base)
    synced["last_event_type"] = "transfer_order"
    # UPDATE matter, INSERT event, sync UPDATE matter
    conn = FakeConn([base, {"id": uuid4()}, synced])
    monkeypatch.setattr(mtq, "connection", fake_connection(conn))
    out = mtq.apply_harvest_write(
        "roblox",
        {"pending_count": 182},
        event={
            "event_type": "transfer_order",
            "event_date": None,
            "cite": "MDL-3166",
            "source_url": "https://example.com/order",
            "summary": "transfer order on free sources",
        },
    )
    assert out["last_event_type"] == "transfer_order"
    assert len(conn.cur.calls) == 3
    assert "INSERT INTO mdl_events" in conn.cur.calls[1][0]
    set_clause = conn.cur.calls[0][0].split("RETURNING", 1)[0]
    assert "human_label" not in set_clause
    assert "invest_score" not in set_clause


def test_matter_harvest_model_excludes_label_score():
    body = MatterHarvestWrite(pending_count=10, notes="n")
    dumped = body.model_dump(exclude_unset=True)
    assert "human_label" not in dumped
    assert "invest_score" not in dumped
    assert dumped["pending_count"] == 10
