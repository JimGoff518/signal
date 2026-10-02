"""Lane B Mass Tort tab (PR3) — nesting helper + template render (no Postgres)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost:5432/x")

from web import app as webapp
from web import mass_tort_queries as mtq


def _matter(**over):
    now = datetime.now(timezone.utc)
    base = dict(
        id=uuid4(),
        slug="ai-litigation",
        caption="AI litigation (umbrella)",
        parent_slug=None,
        human_label="INVEST",
        invest_score=None,
        mdl_or_jccp_id="MDL-3143",
        court="S.D.N.Y.",
        pending_count=19,
        last_event_at=None,
        last_event_type=None,
        source_urls=["https://example.test/a"],
        notes="Umbrella row.",
        priority_rank=1,
        updated_at=now,
        created_at=now,
        cl_filings_delta_7d=None,
        last_verified_at=None,
        nest_depth=0,
    )
    base.update(over)
    return base


def test_nest_matters_child_follows_parent_display_only():
    rows = [
        _matter(slug="ai-litigation", caption="AI", priority_rank=1),
        _matter(
            slug="openai-suicide-pl",
            caption="OpenAI",
            parent_slug="ai-litigation",
            priority_rank=2,
        ),
        _matter(slug="galaxy-gas", caption="Galaxy Gas", priority_rank=3),
    ]
    # Shuffle so nest helper must reattach child after parent.
    shuffled = [rows[1], rows[2], rows[0]]
    out = mtq.nest_matters_for_display(shuffled)
    slugs = [r["slug"] for r in out]
    assert slugs == ["galaxy-gas", "ai-litigation", "openai-suicide-pl"]
    by = {r["slug"]: r for r in out}
    assert by["ai-litigation"]["nest_depth"] == 0
    assert by["openai-suicide-pl"]["nest_depth"] == 1
    assert by["galaxy-gas"]["nest_depth"] == 0
    # Scores never invented / merged.
    assert by["openai-suicide-pl"]["invest_score"] is None
    assert by["ai-litigation"]["invest_score"] is None


def test_nest_orphan_child_stays_top_level_when_parent_filtered_out():
    child = _matter(
        slug="openai-suicide-pl",
        parent_slug="ai-litigation",
        caption="OpenAI",
    )
    out = mtq.nest_matters_for_display([child])
    assert len(out) == 1
    assert out[0]["nest_depth"] == 0
    assert out[0]["parent_slug"] == "ai-litigation"


def _render(name: str, **ctx) -> str:
    return webapp.templates.env.get_template(name).render(**ctx)


def test_mass_tort_list_template_renders_columns_and_filters():
    matters = [
        _matter(),
        _matter(
            slug="openai-suicide-pl",
            caption="OpenAI suicide / product liability",
            parent_slug="ai-litigation",
            mdl_or_jccp_id="JCCP 5431",
            nest_depth=1,
            pending_count=None,
        ),
        _matter(
            slug="pfas-afff",
            caption="PFAS (AFFF)",
            human_label="PASS",  # displays as HOLD
            mdl_or_jccp_id="MDL-2873",
            last_event_type="transfer_order",
            priority_rank=None,
            last_verified_at=datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc),
            source_urls=["https://www.jpml.uscourts.gov/sites/jpml/files/x.pdf"],
        ),
    ]
    html = _render(
        "mass_tort.html",
        title="SIGNAL — Mass tort",
        user="jim",
        active_nav="mass-tort",
        matters=matters,
        total=len(matters),
        selected_label="ALL",
        label_counts={"INVEST": 2, "CHASE": 0, "WATCH": 0, "HOLD": 1},
        label_total=3,
        ticker=None,
        PALETTE=webapp.CLASSIFICATION_PALETTE,
        MT_PALETTE=webapp.MASS_TORT_LABEL_PALETTE,
        MT_LABEL_ORDER=webapp.MASS_TORT_LABEL_ORDER,
        MT_EVENT_LABELS=webapp.MASS_TORT_EVENT_LABELS,
        MT_STAGE_STRIP=webapp.MASS_TORT_STAGE_STRIP,
        mt_decision_label=mtq.decision_label,
        mt_preferred_url=mtq.preferred_source_url,
        mt_stage_label=mtq.stage_strip_label,
    )
    assert "Mass tort" in html
    assert "Decision" in html and "Caption" in html and "Stage" in html
    assert "7d CL" in html and "Last verified" in html and "Link" in html
    # Primary list drops Pending / Last event / Updated.
    assert ">Pending<" not in html.replace(" ", "")
    assert "INVEST" in html and "HOLD" in html
    assert "AI litigation" in html
    assert "OpenAI suicide" in html
    assert "↳" in html  # nest marker
    assert "MDL" in html  # stage strip from transfer_order
    assert "JPML" in html  # preferred link label
    assert "/mass-tort?label=WATCH" in html
    assert "/mass-tort?label=HOLD" in html
    # No NHTSA / Filevine / Jev chrome on this tab.
    assert "NHTSA" not in html
    assert "Filevine" not in html
    assert "Complaint volume" not in html


def test_mass_tort_panel_template_drawer_fields():
    matter = _matter(
        notes="Do not merge with OpenAI row.",
        last_event_type="transfer_order",
        last_verified_at=datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc),
        cl_filings_delta_7d=None,
    )
    events = [
        {
            "id": uuid4(),
            "matter_id": matter["id"],
            "event_type": "transfer_order",
            "event_date": None,
            "cite": "MDL-3143",
            "source_url": "https://example.test/order",
            "summary": "Transfer order entered",
            "created_at": matter["updated_at"],
        }
    ]
    html = _render(
        "_mass_tort_panel.html",
        matter=matter,
        events=events,
        MT_PALETTE=webapp.MASS_TORT_LABEL_PALETTE,
        MT_LABEL_ORDER=webapp.MASS_TORT_LABEL_ORDER,
        MT_EVENT_LABELS=webapp.MASS_TORT_EVENT_LABELS,
        MT_STAGE_STRIP=webapp.MASS_TORT_STAGE_STRIP,
        mt_decision_label=mtq.decision_label,
        mt_preferred_url=mtq.preferred_source_url,
        mt_stage_label=mtq.stage_strip_label,
    )
    assert "AI litigation (umbrella)" in html
    assert "MDL-3143" in html
    assert "S.D.N.Y." in html
    assert "Human label" in html
    assert "Stage" in html and "MDL" in html
    assert "7d CL" in html
    assert "Last verified" in html
    assert "Source links" in html
    assert "https://example.test/a" in html
    assert "Do not merge with OpenAI row." in html
    assert "Event timeline" in html
    assert "Transfer order" in html
    assert "—" in html  # null 7d CL blank
    assert "NHTSA" not in html


def test_mass_tort_routes_require_auth_and_are_registered():
    from fastapi.testclient import TestClient

    client = TestClient(webapp.app, base_url="https://testserver", follow_redirects=False)
    r = client.get("/mass-tort")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    r = client.get("/mass-tort/ai-litigation/panel")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    paths = {getattr(route, "path", None) for route in webapp.app.routes}
    assert "/mass-tort" in paths
    assert "/mass-tort/{slug}/panel" in paths
