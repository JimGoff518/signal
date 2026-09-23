"""Shadow-mode Jev questions for Signal viability memos (START-HERE A+B).

Wire judgments through the TypeSafe Jev System One client behind a thin
adapter. These strings are the product contract — do not change option
values without a migration note (they land in jev_shadow_judgments).
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from signalwarn.config import settings

log = logging.getLogger(__name__)

SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
REQUEST_TIMEOUT_S = 30.0

# ---------------------------------------------------------------------------
# Fixed Choice option values (machine) — keep stable for learning / SQL
# ---------------------------------------------------------------------------

NEXT_HUMAN_ACTION_OPTIONS: tuple[str, ...] = (
    "INVESTIGATE_NOW",
    "MONITOR_CLOSELY",
    "LOW_PRIORITY",
    "SKIP_FILED",
)

NEXT_HUMAN_ACTION_LABELS: dict[str, str] = {
    "INVESTIGATE_NOW": "Investigate now",
    "MONITOR_CLOSELY": "Monitor closely",
    "LOW_PRIORITY": "Low priority",
    "SKIP_FILED": "Skip — class action already filed / opportunity gone",
}

LITIGATION_VEHICLE_OPTIONS: tuple[str, ...] = (
    "CLASS_ACTION",
    "MASS_TORT",
    "MDL",
    "INDIVIDUAL",
    "HYBRID",
)

LITIGATION_VEHICLE_LABELS: dict[str, str] = {
    "CLASS_ACTION": "Class action",
    "MASS_TORT": "Mass tort",
    "MDL": "MDL",
    "INDIVIDUAL": "Individual",
    "HYBRID": "Hybrid (class for economic + individual/mass for PI)",
}


def _fmt(v: Any) -> str:
    if v is None:
        return "unknown"
    return str(v)


def _cluster_header(cluster: Mapping[str, Any]) -> str:
    year = cluster.get("model_year")
    year_bit = "multi-year" if cluster.get("is_multi_year") else _fmt(year)
    return (
        f"{_fmt(cluster.get('make'))} {_fmt(cluster.get('model'))} ({year_bit}) "
        f"/ {_fmt(cluster.get('component'))} — "
        f"score {_fmt(cluster.get('score'))} ({_fmt(cluster.get('classification'))})"
    )


def _numeric_ground_truth(cluster: Mapping[str, Any]) -> str:
    """Embed facts the Noul must check the memo against."""
    lines = [
        f"- complaint_count: {_fmt(cluster.get('complaint_count'))}",
        f"- injury_count: {_fmt(cluster.get('injury_count'))}",
        f"- death_count: {_fmt(cluster.get('death_count'))}",
        f"- crash_count: {_fmt(cluster.get('crash_count'))}",
        f"- fire_count: {_fmt(cluster.get('fire_count'))}",
        f"- velocity_30d: {_fmt(cluster.get('velocity_30d'))}",
        f"- velocity_7d: {_fmt(cluster.get('velocity_7d'))}",
        f"- first_complaint_date: {_fmt(cluster.get('first_complaint_date'))}",
        f"- last_complaint_date: {_fmt(cluster.get('last_complaint_date'))}",
        f"- tx_complaint_count: {_fmt(cluster.get('tx_complaint_count'))}",
        f"- time_barred_count: {_fmt(cluster.get('time_barred_count'))}",
    ]
    ewr_d = cluster.get("ewr_death_count") or 0
    ewr_i = cluster.get("ewr_injury_count") or 0
    ewr_n = cluster.get("ewr_incident_count") or 0
    if ewr_d or ewr_i or ewr_n:
        lines.append(f"- ewr_incident_count: {_fmt(ewr_n)}")
        lines.append(f"- ewr_death_count: {_fmt(ewr_d)}")
        lines.append(f"- ewr_injury_count: {_fmt(ewr_i)}")
    return "\n".join(lines)


def _filed_context(cluster: Mapping[str, Any]) -> str:
    filed = bool(cluster.get("class_action_filed"))
    same = bool(cluster.get("class_action_same_defect"))
    if filed and same:
        return (
            "FILED FLAG: a class action is marked filed AND same-defect for this cluster. "
            "Prefer SKIP_FILED unless the memo shows the opportunity is still open."
        )
    if filed and not same:
        return (
            "FILED FLAG: a vehicle-level class action exists but may NOT name this defect "
            f"(case: {_fmt(cluster.get('class_action_case_name'))}). "
            "SKIP_FILED is available but not automatic."
        )
    return "FILED FLAG: no class_action_filed on this cluster."


def _memo_block(memo_text: str, claude_recommended_action: str | None) -> str:
    action_line = ""
    if claude_recommended_action:
        action_line = f"\nClaude memo said RECOMMENDED ACTION: {claude_recommended_action}\n"
    return f"{action_line}\n--- VIABILITY MEMO ---\n{memo_text}\n--- END MEMO ---"


def build_next_human_action_question(
    cluster: Mapping[str, Any],
    memo_text: str,
    *,
    claude_recommended_action: str | None = None,
) -> dict[str, Any]:
    """Choice: what should Goff Law do next with this opportunity."""
    question = (
        "Given this NHTSA complaint cluster and the Claude viability memo below, "
        "what should a plaintiff's attorney at Goff Law do NEXT with this opportunity?\n\n"
        "Prefer SKIP_FILED only when a class action already covers this same defect "
        "(or the opportunity is clearly gone). "
        "Prefer INVESTIGATE_NOW only when volume, severity, and memo reasoning justify "
        "immediate human work. "
        "Prefer MONITOR_CLOSELY when the signal is real but not urgent. "
        "Prefer LOW_PRIORITY when numerosity, commonality, or timing look weak.\n\n"
        f"Cluster: {_cluster_header(cluster)}\n"
        f"{_filed_context(cluster)}\n"
        f"Ground-truth counts:\n{_numeric_ground_truth(cluster)}\n"
        f"{_memo_block(memo_text, claude_recommended_action)}"
    )
    return {
        "kind": "choice",
        "name": "next_human_action",
        "question": question,
        "options": list(NEXT_HUMAN_ACTION_OPTIONS),
        "option_labels": dict(NEXT_HUMAN_ACTION_LABELS),
    }


def build_litigation_vehicle_question(
    cluster: Mapping[str, Any],
    memo_text: str,
) -> dict[str, Any]:
    """Choice: best litigation vehicle for early-warning triage."""
    question = (
        "Which litigation vehicle best fits these facts for Goff Law's early-warning use case?\n\n"
        "CLASS_ACTION when uniform economic loss and Rule 23 predominance look workable. "
        "MASS_TORT when individualized injury dominates. "
        "MDL when multi-district coordination is the realistic path. "
        "INDIVIDUAL when volume or commonality cannot support aggregate treatment. "
        "HYBRID when class for economic claims plus individual/mass tort for personal injury.\n\n"
        f"Cluster: {_cluster_header(cluster)}\n"
        f"Ground-truth counts:\n{_numeric_ground_truth(cluster)}\n"
        f"{_memo_block(memo_text, None)}"
    )
    return {
        "kind": "choice",
        "name": "litigation_vehicle",
        "question": question,
        "options": list(LITIGATION_VEHICLE_OPTIONS),
        "option_labels": dict(LITIGATION_VEHICLE_LABELS),
    }


def build_memo_matches_facts_question(
    cluster: Mapping[str, Any],
    memo_text: str,
) -> dict[str, Any]:
    """Noul: does the memo's quantitative claims match cluster state?"""
    question = (
        "Does the viability memo's claims about complaint volume, injuries, deaths, "
        "crashes, fires, velocity, and date range MATCH the numeric cluster state "
        "provided (no invented or grossly wrong counts)?\n\n"
        "Answer YES only if the memo's quantitative claims are consistent with the "
        "numbers below within ordinary rounding or paraphrase. "
        "Answer NO if the memo invents counts, inflates injuries or deaths, or cites "
        "volume that contradicts the cluster state.\n\n"
        f"Cluster: {_cluster_header(cluster)}\n"
        f"Ground-truth numbers (source of truth):\n{_numeric_ground_truth(cluster)}\n"
        f"{_memo_block(memo_text, None)}"
    )
    return {
        "kind": "noul",
        "name": "memo_matches_facts",
        "question": question,
    }


def build_safe_to_surface_question(
    cluster: Mapping[str, Any],
    memo_text: str,
) -> dict[str, Any]:
    """Noul: is the memo safe to show a lawyer as a decision aid?"""
    question = (
        "Is this memo safe to show a lawyer as a DECISION AID without obvious "
        "hallucinated case citations, fake docket numbers, or fabricated statutes?\n\n"
        "The memo may reason about Texas DTPA, warranty, or defect theories at a high "
        "level. Answer YES only if there are no clear fake authorities or invented "
        "specific holdings. Answer NO if you see specific case names, reporters, or "
        "dockets that look fabricated or unverifiable from the provided materials alone.\n\n"
        f"Cluster: {_cluster_header(cluster)}\n"
        f"{_memo_block(memo_text, None)}"
    )
    return {
        "kind": "noul",
        "name": "safe_to_surface",
        "question": question,
    }


def build_shadow_batch(
    cluster: Mapping[str, Any],
    memo_text: str,
    *,
    states: Sequence[str] | None = None,
    sample_descriptions: Sequence[str] | None = None,
    claude_recommended_action: str | None = None,
) -> list[dict[str, Any]]:
    """Assemble the four-judgment batch for one newly written memo.

    `states` and `sample_descriptions` are reserved for later narrative Nouls;
    A+B shadow does not send them to Jev yet but callers should pass them so
    the payload builder can log them beside the row if desired.
    """
    _ = states, sample_descriptions  # available to storage / future seams
    return [
        build_next_human_action_question(
            cluster, memo_text, claude_recommended_action=claude_recommended_action
        ),
        build_litigation_vehicle_question(cluster, memo_text),
        build_memo_matches_facts_question(cluster, memo_text),
        build_safe_to_surface_question(cluster, memo_text),
    ]


# ---------------------------------------------------------------------------
# Adapter — TypeSafe System One over HTTP. Logs only; no DB writes yet.
# ---------------------------------------------------------------------------


def build_request(batch: Sequence[Mapping[str, Any]], cluster_id: int) -> dict[str, Any]:
    """Translate a shadow batch into a System One request body.

    Each question string is self-contained (cluster facts + memo), so state
    only carries the cluster id.
    """
    questions: dict[str, Any] = {}
    for q in batch:
        if q["kind"] == "choice":
            questions[q["name"]] = {
                "type": "choice",
                "instructions": q["question"],
                "criteria": {opt: q["option_labels"][opt] for opt in q["options"]},
            }
        else:
            questions[q["name"]] = {"type": "noul", "instructions": q["question"]}
    return {
        "model": settings.jev_model,
        "state": {"cluster_id": cluster_id},
        "questions": questions,
    }


def summarize_answers(body: Mapping[str, Any]) -> dict[str, Any]:
    """Keep what's worth logging from each answer: the pick and how sure Jev was."""
    out: dict[str, Any] = {}
    for name, ans in (body.get("answers") or {}).items():
        if ans.get("type") == "choice":
            out[name] = {
                "choice": ans.get("choice"),
                "confidence": ans.get("confidence"),
                "probabilities": ans.get("probabilities"),
            }
        else:
            out[name] = {"noul": ans.get("noul")}
    return out


def run_jev_shadow_batch(
    cluster_id: int,
    cluster: Mapping[str, Any],
    memo_text: str,
    *,
    states: Sequence[str] | None = None,
    sample_descriptions: Sequence[str] | None = None,
    claude_recommended_action: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """Send the four shadow questions for a fresh memo and log one JSON line.

    Fails open: any error is logged and swallowed so memo generation never
    sees it. Returns the logged record (for tests), or None when disabled.
    """
    if not settings.jev_shadow_enabled:
        return None
    record: dict[str, Any] = {
        "cluster_id": cluster_id,
        "model": settings.jev_model,
        "claude_recommended_action": claude_recommended_action,
    }
    started = time.monotonic()
    try:
        if not settings.typesafe_api_key:
            raise RuntimeError("TYPESAFE_API_KEY is not set")
        batch = build_shadow_batch(
            cluster,
            memo_text,
            states=states,
            sample_descriptions=sample_descriptions,
            claude_recommended_action=claude_recommended_action,
        )
        payload = build_request(batch, cluster_id)
        headers = {"Authorization": f"Bearer {settings.typesafe_api_key}"}
        if client is None:
            with httpx.Client(timeout=REQUEST_TIMEOUT_S) as c:
                resp = c.post(SYSTEM_ONE_URL, json=payload, headers=headers)
        else:
            resp = client.post(SYSTEM_ONE_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        record["ok"] = True
        record["model"] = body.get("model", record["model"])
        record["answers"] = summarize_answers(body)
        record["usage"] = body.get("usage")
    except Exception as e:
        record["ok"] = False
        record["error"] = f"{type(e).__name__}: {e}"
    record["latency_ms"] = round((time.monotonic() - started) * 1000)
    try:
        log.info("jev_shadow %s", json.dumps(record, default=str))
    except Exception:
        log.warning("jev_shadow logging failed for cluster %s", cluster_id)
    return record
