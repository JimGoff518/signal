"""Shadow-mode Jev: question batch contract and the logs-only adapter."""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from signalwarn import jev_shadow
from signalwarn.config import settings
from signalwarn.jev_shadow import build_shadow_batch

MEMO = "Strong numerosity.\nRECOMMENDED ACTION: INVESTIGATE NOW\n"


def _cluster(**overrides):
    base = {
        "make": "FORD",
        "model": "EXPLORER",
        "model_year": 2020,
        "is_multi_year": False,
        "component": "POWERTRAIN",
        "score": 72,
        "classification": "HOT",
        "complaint_count": 140,
        "injury_count": 3,
        "death_count": 0,
        "crash_count": 5,
        "fire_count": 0,
        "velocity_30d": 22,
        "velocity_7d": 6,
        "first_complaint_date": "2023-01-04",
        "last_complaint_date": "2026-09-01",
        "tx_complaint_count": 11,
        "time_barred_count": 2,
        "class_action_filed": False,
        "class_action_same_defect": False,
        "class_action_case_name": None,
    }
    base.update(overrides)
    return base


def _by_name(batch):
    return {q["name"]: q for q in batch}


def test_batch_has_four_questions_in_order():
    batch = build_shadow_batch(_cluster(), MEMO, claude_recommended_action="INVESTIGATE NOW")
    assert [(q["name"], q["kind"]) for q in batch] == [
        ("next_human_action", "choice"),
        ("litigation_vehicle", "choice"),
        ("memo_matches_facts", "noul"),
        ("safe_to_surface", "noul"),
    ]


def test_option_values_are_the_fixed_contract():
    qs = _by_name(build_shadow_batch(_cluster(), MEMO))
    assert qs["next_human_action"]["options"] == [
        "INVESTIGATE_NOW",
        "MONITOR_CLOSELY",
        "LOW_PRIORITY",
        "SKIP_FILED",
    ]
    assert qs["litigation_vehicle"]["options"] == [
        "CLASS_ACTION",
        "MASS_TORT",
        "MDL",
        "INDIVIDUAL",
        "HYBRID",
    ]
    for name in ("next_human_action", "litigation_vehicle"):
        q = qs[name]
        assert set(q["option_labels"]) == set(q["options"])
    for name in ("memo_matches_facts", "safe_to_surface"):
        assert "options" not in qs[name]


def test_question_text_carries_paragraph_breaks_memo_and_facts():
    qs = _by_name(build_shadow_batch(_cluster(), MEMO, claude_recommended_action="INVESTIGATE NOW"))
    for q in qs.values():
        assert "?\n\n" in q["question"]
        assert "--- VIABILITY MEMO ---\n" + MEMO in q["question"]
    nha = qs["next_human_action"]["question"]
    assert "Claude memo said RECOMMENDED ACTION: INVESTIGATE NOW" in nha
    assert "- complaint_count: 140" in nha
    assert "FORD EXPLORER (2020) / POWERTRAIN — score 72 (HOT)" in nha
    assert "Claude memo said" not in qs["litigation_vehicle"]["question"]


def test_filed_flag_wording_not_filed():
    q = _by_name(build_shadow_batch(_cluster(), MEMO))["next_human_action"]["question"]
    assert "FILED FLAG: no class_action_filed on this cluster." in q


def test_filed_flag_wording_filed_same_defect():
    cluster = _cluster(class_action_filed=True, class_action_same_defect=True)
    q = _by_name(build_shadow_batch(cluster, MEMO))["next_human_action"]["question"]
    assert "marked filed AND same-defect" in q
    assert "Prefer SKIP_FILED unless the memo shows the opportunity is still open." in q


def test_filed_flag_wording_filed_other_defect_names_case():
    cluster = _cluster(
        class_action_filed=True,
        class_action_same_defect=False,
        class_action_case_name="Doe v. Ford Motor Co.",
    )
    q = _by_name(build_shadow_batch(cluster, MEMO))["next_human_action"]["question"]
    assert "may NOT name this defect (case: Doe v. Ford Motor Co.)" in q
    assert "SKIP_FILED is available but not automatic." in q


def test_filed_flag_only_on_next_human_action():
    cluster = _cluster(class_action_filed=True, class_action_same_defect=True)
    qs = _by_name(build_shadow_batch(cluster, MEMO))
    for name in ("litigation_vehicle", "memo_matches_facts", "safe_to_surface"):
        assert "FILED FLAG" not in qs[name]["question"]


def test_ewr_lines_appear_only_when_present():
    without = _by_name(build_shadow_batch(_cluster(), MEMO))["memo_matches_facts"]["question"]
    assert "ewr_" not in without
    with_ewr = _by_name(build_shadow_batch(_cluster(ewr_death_count=2), MEMO))[
        "memo_matches_facts"
    ]["question"]
    assert "- ewr_death_count: 2" in with_ewr
    assert "- ewr_incident_count: 0" in with_ewr


def test_multi_year_header_and_missing_values():
    cluster = _cluster(model_year=None, is_multi_year=True, velocity_7d=None)
    q = _by_name(build_shadow_batch(cluster, MEMO))["litigation_vehicle"]["question"]
    assert "FORD EXPLORER (multi-year) / POWERTRAIN" in q
    assert "- velocity_7d: unknown" in q


# ---------------------------------------------------------------------------
# Adapter: request shape, logged record, fail-open
# ---------------------------------------------------------------------------

OK_BODY = {
    "model": "jev-1.13.0",
    "answers": {
        "next_human_action": {
            "type": "choice",
            "choice": "MONITOR_CLOSELY",
            "probabilities": {"INVESTIGATE_NOW": 0.3, "MONITOR_CLOSELY": 0.6},
            "confidence": 0.55,
        },
        "litigation_vehicle": {
            "type": "choice",
            "choice": "CLASS_ACTION",
            "probabilities": {"CLASS_ACTION": 0.9},
            "confidence": 0.8,
        },
        "memo_matches_facts": {"type": "noul", "noul": 0.93},
        "safe_to_surface": {"type": "noul", "noul": 0.71},
    },
    "usage": {"input_tokens": 4000, "output_tokens": 40},
}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "jev_shadow_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-key")
    monkeypatch.setattr(settings, "jev_model", "jev-1.13.0")


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_disabled_by_default_makes_no_call(monkeypatch):
    monkeypatch.setattr(settings, "jev_shadow_enabled", False)

    def handler(request):
        raise AssertionError("should not call TypeSafe when disabled")

    assert jev_shadow.run_jev_shadow_batch(1, _cluster(), MEMO, client=_client(handler)) is None


def test_request_body_and_logged_answers(enabled, caplog):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    with caplog.at_level(logging.INFO, logger="signalwarn.jev_shadow"):
        rec = jev_shadow.run_jev_shadow_batch(
            42, _cluster(), MEMO, claude_recommended_action="INVESTIGATE NOW",
            client=_client(handler),
        )

    body = seen["body"]
    assert seen["auth"] == "Bearer test-key"
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == {"cluster_id": 42}
    qs = body["questions"]
    assert list(qs) == [
        "next_human_action", "litigation_vehicle", "memo_matches_facts", "safe_to_surface",
    ]
    assert qs["next_human_action"]["type"] == "choice"
    assert list(qs["next_human_action"]["criteria"]) == [
        "INVESTIGATE_NOW", "MONITOR_CLOSELY", "LOW_PRIORITY", "SKIP_FILED",
    ]
    assert qs["memo_matches_facts"] == {
        "type": "noul", "instructions": qs["memo_matches_facts"]["instructions"],
    }

    assert rec["ok"] is True
    assert rec["cluster_id"] == 42
    assert rec["claude_recommended_action"] == "INVESTIGATE NOW"
    assert rec["answers"]["next_human_action"]["choice"] == "MONITOR_CLOSELY"
    assert rec["answers"]["next_human_action"]["confidence"] == 0.55
    assert rec["answers"]["safe_to_surface"] == {"noul": 0.71}

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("jev_shadow ")]
    assert len(lines) == 1
    assert json.loads(lines[0].removeprefix("jev_shadow "))["cluster_id"] == 42


@pytest.mark.parametrize(
    "handler",
    [
        lambda req: httpx.Response(529, text="overloaded"),
        lambda req: (_ for _ in ()).throw(httpx.ConnectTimeout("timed out")),
        lambda req: httpx.Response(200, text="not json"),
    ],
    ids=["http-error", "timeout", "bad-json"],
)
def test_failures_are_logged_not_raised(enabled, caplog, handler):
    with caplog.at_level(logging.INFO, logger="signalwarn.jev_shadow"):
        rec = jev_shadow.run_jev_shadow_batch(7, _cluster(), MEMO, client=_client(handler))
    assert rec["ok"] is False
    assert rec["error"]
    assert any("jev_shadow " in r.getMessage() and '"ok": false' in r.getMessage()
               for r in caplog.records)


def test_missing_api_key_fails_open(enabled, monkeypatch):
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    rec = jev_shadow.run_jev_shadow_batch(7, _cluster(), MEMO)
    assert rec["ok"] is False
    assert "TYPESAFE_API_KEY" in rec["error"]
