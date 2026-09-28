"""Pure-function tests for the /investigate research helpers (no DB)."""
from __future__ import annotations

from datetime import date

import pytest

from signalwarn import research


def test_recommended_action_parses_memo_line():
    memo = "CASE TYPE: CLASS ACTION\n...\nRECOMMENDED ACTION: INVESTIGATE NOW\n\nKeep it short."
    assert research.recommended_action(memo) == "INVESTIGATE NOW"


def test_recommended_action_strips_brackets_and_trailing_prose():
    memo = "RECOMMENDED ACTION: [MONITOR CLOSELY] — volume still climbing."
    assert research.recommended_action(memo) == "MONITOR CLOSELY"


def test_recommended_action_none_when_absent():
    assert research.recommended_action(None) is None
    assert research.recommended_action("No action line here.") is None


def test_candidates_query_targets_unresearched_critical_and_hot():
    sql, params = research.candidates_query(limit=7)
    assert "research_memo IS NULL" in sql
    assert "'CRITICAL'" in sql and "'HOT'" in sql
    assert "class_action_status" in sql  # terminated / cert_denied are not open-cert research targets
    assert "cert_denied" in sql
    assert "ORDER BY" in sql and "score DESC" in sql
    assert params == {"limit": 7}


def test_save_research_rejects_empty_text_before_touching_db():
    with pytest.raises(ValueError):
        research.save_research(1, "   \n")


def test_format_show_includes_facts_memo_and_narratives():
    cluster = dict(
        id=42,
        make="FORD",
        model="FOCUS",
        model_year=None,
        is_multi_year=True,
        component="POWER TRAIN",
        complaint_count=812,
        injury_count=4,
        death_count=0,
        crash_count=9,
        fire_count=0,
        velocity_30d=31,
        score=97,
        classification="CRITICAL",
        recall_issued=False,
        nhtsa_investigation_open=True,
        class_action_filed=True,
        class_action_status="pending",
        class_action_case_name="Doe v. Ford",
        class_action_court="E.D. Mich.",
        class_action_url="https://example.test/doe",
        first_complaint_date=date(2016, 1, 4),
        last_complaint_date=date(2026, 9, 1),
        viability_memo="CASE TYPE: CLASS ACTION\nRECOMMENDED ACTION: INVESTIGATE NOW",
        research_memo=None,
    )
    out = research.format_show(
        cluster,
        states=["TX", "CA"],
        narratives=[
            {
                "date_complaint_filed": date(2026, 8, 2),
                "state": "TX",
                "description": "Transmission shudders at low speed.",
            }
        ],
    )
    assert "Cluster 42" in out and "FORD FOCUS" in out and "multi-year" in out
    assert "POWER TRAIN" in out and "812" in out
    assert "TX, CA" in out
    assert "Doe v. Ford" in out and "pending" in out
    assert "Transmission shudders" in out
    assert "INVESTIGATE NOW" in out


def test_format_show_says_when_there_is_no_memo():
    cluster = dict(
        id=1, make="KIA", model="SOUL", model_year=2017, is_multi_year=False,
        component="ENGINE", complaint_count=20, injury_count=0, death_count=0,
        crash_count=0, fire_count=2, velocity_30d=1, score=55, classification="WATCH",
        recall_issued=True, nhtsa_investigation_open=False, class_action_filed=False,
        class_action_status=None, class_action_case_name=None, class_action_court=None,
        class_action_url=None, first_complaint_date=None, last_complaint_date=None,
        viability_memo=None, research_memo=None,
    )
    out = research.format_show(cluster, states=[], narratives=[])
    assert "(no viability memo)" in out
    assert "(no narratives on file)" in out
