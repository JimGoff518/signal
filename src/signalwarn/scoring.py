"""Scoring engine — assigns 0-100 to each complaint cluster.

Formula faithfully matches docs/SIGNAL_TECHNICAL_SPEC.md §7.2, with one fix:
the spec's velocity branches are checked in the wrong order (the 0.5 doubled
condition would always shadow the 0.66 tripled condition). We check tripled
first so the larger multiplier wins when both apply.
"""
from __future__ import annotations

from dataclasses import dataclass

# Classification thresholds (spec §7.3, lower bound inclusive).
_THRESHOLDS = (
    (90, "CRITICAL"),
    (70, "HOT"),
    (50, "WATCH"),
    (25, "MONITOR"),
    (0, "NOISE"),
)


@dataclass
class ClusterFacts:
    """Inputs to the scoring formula. One per cluster row."""
    complaint_count: int = 0
    velocity_30d: int = 0
    injury_count: int = 0
    death_count: int = 0
    crash_count: int = 0
    fire_count: int = 0
    is_multi_year: bool = False
    nhtsa_investigation_open: bool = False
    recall_issued: bool = False
    class_action_filed: bool = False


def compute_score(facts: ClusterFacts) -> int:
    """Return a 0-100 score for the given cluster facts."""
    # BASE — volume, capped at 30.
    score = min(facts.complaint_count, 30)

    # VELOCITY — check tripled first so it isn't shadowed by doubled.
    count = facts.complaint_count
    v30 = facts.velocity_30d
    if v30 > 0 and count > 0:
        if v30 >= count * 0.66:
            score *= 3
        elif v30 >= count * 0.5:
            score *= 2

    # SEVERITY ESCALATORS
    if facts.injury_count > 0:
        score += 20
    if facts.death_count > 0:
        score += 50
    if facts.crash_count > 0:
        score += 10
    if facts.fire_count > 0:
        score += 15

    # CROSS-YEAR SIGNAL
    if facts.is_multi_year:
        score += 10

    # NHTSA INVESTIGATION / RECALL / EXISTING CLASS ACTION
    if facts.nhtsa_investigation_open:
        score += 20
    if facts.recall_issued:
        score += 25
    if facts.class_action_filed:
        score -= 30

    return max(0, min(100, score))


def classify(score: int) -> str:
    """Return CRITICAL / HOT / WATCH / MONITOR / NOISE for a score."""
    for lower, label in _THRESHOLDS:
        if score >= lower:
            return label
    return "NOISE"
