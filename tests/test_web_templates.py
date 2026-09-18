"""Render every dashboard template against a fake context.

No database: this only proves the Jinja templates compile and that every
variable / palette key they reference is supplied by the routes. A missing
context key or a typo in a macro fails here instead of as a 500 in prod.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost:5432/x")

from web import app as webapp  # env must be set before this import
from web import queries

TODAY = date.today()


def _cluster(**over):
    base = dict(
        id=7,
        make="FORD",
        model="F-150",
        model_year=2019,
        component="ENGINE",
        is_multi_year=False,
        complaint_count=412,
        injury_count=3,
        death_count=0,
        crash_count=5,
        fire_count=1,
        velocity_30d=18,
        score=84,
        classification="HOT",
        first_complaint_date=date(2019, 3, 1),
        last_complaint_date=TODAY,
        recall_issued=True,
        nhtsa_investigation_open=False,
        class_action_filed=True,
        class_action_status="pending",
        class_action_case_name="Doe v. Ford Motor Co.",
        class_action_court="E.D. Mich.",
        class_action_filed_date=date(2024, 1, 5),
        class_action_url="https://example.test/x",
        viability_memo="Numerosity looks strong.",
        memo_generated_at=datetime(2026, 5, 9, 14, 3),
        has_memo=True,
        days_since_last=0,
        sparkline=[1, 4, 2, 0, 3],
        sparkline_max=4,
    )
    base.update(over)
    return base


def _render(name: str, **ctx) -> str:
    return webapp.templates.env.get_template(name).render(**ctx)


def _dashboard_ctx(**over):
    sparks = {k: [0, 2, 5, 3, 1, 0, 4, 6, 2, 1, 0, 3] for k in webapp.CLASSIFICATION_ORDER}
    ctx = dict(
        title="SIGNAL",
        user="jim",
        clusters=[
            _cluster(),
            _cluster(
                id=8,
                classification="CRITICAL",
                score=100,
                model_year=None,
                is_multi_year=True,
                has_memo=False,
                class_action_filed=False,
            ),
        ],
        total=2,
        counts={"CRITICAL": 1, "HOT": 1},
        stat_sparks=sparks,
        makes=["FORD", "TOYOTA"],
        years=[2020, 2019],
        components=["ENGINE", "BRAKES"],
        selected_window="Past 6 months",
        selected_make=None,
        selected_year=None,
        selected_component=None,
        selected_recall="",
        selected_filed="",
        selected_sort="score",
        selected_direction="desc",
        sort_default_dir=queries.SORT_DEFAULT_DIR,
        selected_classification="ALL",
        q="",
        page=1,
        last_page=1,
        page_size=50,
        base_qs="",
        filters_qs="window=Past+6+months",
        last_ingestion=None,
        ticker={
            "complaints_scanned": 1000,
            "clusters_tracked": 50,
            "memos_written": 4,
            "last_refresh": datetime(2026, 9, 1, 2, 0),
        },
    )
    ctx.update(over)
    return ctx


@pytest.fixture
def chart_ctx(monkeypatch):
    """_chart_context hits the DB for the breakdowns; stub those two queries."""
    monkeypatch.setattr(
        queries,
        "breakdown_in_view",
        lambda column, limit=8, **f: [{"label": "ENGINE", "n": 12}, {"label": "BRAKES", "n": 3}],
    )
    monkeypatch.setattr(
        queries,
        "signal_counts_in_view",
        lambda **f: {"clusters": 15, "recall": 4, "probe": 1, "filed": 2, "memo": 6},
    )
    sparks = {k: [0, 2, 5, 3, 1, 0, 4, 6, 2, 1, 0, 3] for k in webapp.CLASSIFICATION_ORDER}
    return webapp._chart_context(sparks, {})


def test_dashboard_renders_with_charts_and_filters(chart_ctx):
    html = _render("dashboard.html", **_dashboard_ctx(**chart_ctx))
    # new filters are wired with real labels
    for fid in (
        "f-window",
        "f-make",
        "f-year",
        "f-component",
        "f-class",
        "f-recall",
        "f-filed",
        "f-q",
    ):
        assert f'for="{fid}"' in html and f'id="{fid}"' in html
    # sortable headers expose aria-sort on the active column only
    assert html.count("aria-sort=") == 1 and 'aria-sort="descending"' in html
    # every row has a real link to its cluster page
    assert html.count('class="row-link') == 2
    # charts: volume paths + both breakdowns + signals strip
    assert '<path d="M' in html and "vol-hit" in html
    assert "By component" in html and "By make" in html
    assert "class action pending" in html
    # score meter renders 10 segments per row, lit count matches score
    assert html.count('<span class="meter') >= 2
    # tags: filed + memo pills, no redundant multi-year pill
    assert ">filed<" in html and ">memo<" in html and "multi-year" not in html.lower()
    # no stale globals
    assert "CLASSIFICATION_BADGE" not in html


def test_dashboard_empty_state_offers_reset(chart_ctx):
    html = _render(
        "dashboard.html", **_dashboard_ctx(clusters=[], total=0, selected_make="FORD", **chart_ctx)
    )
    assert "No clusters match these filters." in html and "Reset filters" in html


def test_panel_and_search_results_render():
    c = _cluster()
    html = _render(
        "_panel.html",
        cluster=c,
        complaints=[
            {
                "date_complaint_filed": TODAY,
                "state": "TX",
                "crash": True,
                "deaths": 0,
                "injuries": 1,
                "description": "x" * 300,
            }
        ],
        states=["TX", "CA"],
        volume=[{"month": date(2026, 8, 1), "n": 3}, {"month": date(2026, 9, 1), "n": 5}],
        total_complaints=412,
    )
    assert 'id="panel-title"' in html and "data-autofocus" in html and "Doe v. Ford" in html
    res = _render("_search_results.html", q="ford", results=[c])
    assert 'role="option"' in res and "F-150" in res
    assert "No matches" in _render("_search_results.html", q="zzz", results=[])
    assert "Type to search" in _render("_search_results.html", q="", results=[])


def test_cluster_login_admin_render():
    html = _render(
        "cluster.html",
        title="x",
        user="jim",
        cluster=_cluster(),
        complaints=[],
        states=[],
        volume=[],
        page=1,
        last_page=1,
        total_complaints=0,
        ticker=None,
    )
    assert (
        "Class action pending" in html and "View as table" not in html
    )  # no volume -> no table toggle
    assert "Sign in" in _render("login.html", error="invalid", title="Sign in")
    status = {
        k: {
            "state": "idle",
            "started_at": None,
            "finished_at": None,
            "summary": None,
            "args": None,
            "error": None,
        }
        for k in ("check_filings", "rescore_all", "refresh_complaints")
    }
    req = SimpleNamespace(query_params={"msg": "started"})
    html = _render("admin.html", title="x", user="jim", status=status, request=req, ticker=None)
    assert "Task started" in html and 'for="min-score"' in html
    assert 'for="lookback-days"' in html and "/admin/refresh-complaints" in html


def test_palette_values_are_full_class_strings():
    """Tailwind's scanner only emits classes it sees verbatim in app.py."""
    for tier, spec in webapp.CLASSIFICATION_PALETTE.items():
        for key in ("text", "dot", "bar", "spark", "spark_stat", "badge"):
            assert spec[key], (tier, key)
            for cls in spec[key].split():
                assert "-" in cls and not cls.endswith("-"), (tier, key, cls)


def test_memos_page_renders_and_header_tab_is_active():
    long_memo = "Numerosity: strong. " * 60  # > 600 chars -> collapsible
    rows = [
        {
            **_cluster(),
            "new_since_memo": 40,
            "memo_complaint_count_at_gen": 372,
            "viability_memo": long_memo,
        },
        {
            **_cluster(
                id=9,
                class_action_status="terminated",
                class_action_filed=True,
                viability_memo="Short memo.",
                memo_generated_at=None,
            ),
            "new_since_memo": 0,
        },
    ]
    html = _render(
        "memos.html",
        title="x",
        user="jim",
        active_nav="memos",
        memos=rows,
        total=2,
        q="",
        page=1,
        last_page=1,
        page_size=25,
        ticker=None,
    )
    assert 'aria-current="page"' in html and ">Memos</a>" in html
    assert "Read the full memo" in html and "+40 since memo" in html
    assert ">case closed<" in html
    assert html.count('href="/cluster/7"') >= 2
    empty = _render(
        "memos.html",
        title="x",
        user="jim",
        active_nav="memos",
        memos=[],
        total=0,
        q="brakes",
        page=1,
        last_page=1,
        page_size=25,
        ticker=None,
    )
    assert "No memos mention" in empty
