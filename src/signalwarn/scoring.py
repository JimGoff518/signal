"""Scoring engine — assigns 0-100 to each complaint cluster.

Formula matches docs/SIGNAL_TECHNICAL_SPEC.md §7.2 (rebalanced 2026-05-09 to
prioritize Rule 23 class-certification signals over mass-tort severity). Two
intentional deltas from the original spec:
1. Velocity branches are checked tripled-first so the larger multiplier wins
   when both apply (the spec v1.0 had them reversed, which would always shadow
   the 0.66 case under the 0.5 case).
2. The 2026-05-09 rebalance lifts numerosity/commonality/manufacturer-knowledge
   weights and reduces severity weights — see commit history for the rationale.

The class-action lens is primary; mass tort is secondary. Severe individual
injury defeats predominance under *Amchem*, so death/injury escalators stay in
scope but no longer dominate the score.
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
    # ── NUMEROSITY — Rule 23(a)(1). Volume is THE class-action signal. ──
    score = min(facts.complaint_count, 50)

    # ── VELOCITY — check tripled first so it isn't shadowed by doubled. ──
    count = facts.complaint_count
    v30 = facts.velocity_30d
    if v30 > 0 and count > 0:
        if v30 >= count * 0.66:
            score *= 3
        elif v30 >= count * 0.5:
            score *= 2

    # ── COMMONALITY — Rule 23(a)(2). Multi-year systemic defect. ──
    if facts.is_multi_year:
        score += 20

    # ── MANUFACTURER KNOWLEDGE — failure-to-warn / scienter foundation. ──
    if facts.nhtsa_investigation_open:
        score += 25
    if facts.recall_issued:
        score += 30

    # ── SEVERITY ESCALATORS — secondary (mass-tort lens). Reduced weights. ──
    if facts.injury_count > 0:
        score += 10
    if facts.death_count > 0:
        score += 20
    if facts.crash_count > 0:
        score += 5
    if facts.fire_count > 0:
        score += 10

    # ── EXISTING CLASS ACTION PENALTY — we want to be early. ──
    if facts.class_action_filed:
        score -= 30

    return max(0, min(100, score))


def classify(score: int) -> str:
    """Return CRITICAL / HOT / WATCH / MONITOR / NOISE for a score."""
    for lower, label in _THRESHOLDS:
        if score >= lower:
            return label
    return "NOISE"
