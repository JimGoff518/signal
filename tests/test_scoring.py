"""Tests for the 0-100 scoring engine and classifier."""
from __future__ import annotations

import pytest

from signalwarn.scoring import ClusterFacts, classify, compute_score


# ─── Base score (volume) ────────────────────────────────────────────────

def test_empty_cluster_scores_zero():
    assert compute_score(ClusterFacts()) == 0


def test_volume_under_cap_contributes_one_per_complaint():
    assert compute_score(ClusterFacts(complaint_count=10)) == 10


def test_volume_caps_at_fifty():
    """Numerosity cap raised from 30 to 50 in the 2026-05-09 class-action rebalance."""
    assert compute_score(ClusterFacts(complaint_count=500)) == 50


# ─── Velocity multipliers ───────────────────────────────────────────────

def test_velocity_doubled_applies_2x_to_base():
    facts = ClusterFacts(complaint_count=20, velocity_30d=10)  # 50% in last 30d
    assert compute_score(facts) == 40  # 20 base × 2


def test_velocity_tripled_applies_3x_to_base():
    facts = ClusterFacts(complaint_count=20, velocity_30d=14)  # 70%
    assert compute_score(facts) == 60  # 20 base × 3


def test_velocity_zero_applies_no_multiplier():
    facts = ClusterFacts(complaint_count=20, velocity_30d=0)
    assert compute_score(facts) == 20


def test_velocity_below_doubled_threshold_applies_no_multiplier():
    facts = ClusterFacts(complaint_count=20, velocity_30d=6)  # 30%
    assert compute_score(facts) == 20


# ─── Severity escalators ────────────────────────────────────────────────

def test_injury_adds_ten():
    """Class-action lens: injury weight reduced from 20→10 in the 2026-05-09 rebalance."""
    assert compute_score(ClusterFacts(complaint_count=10, injury_count=1)) == 20


def test_death_adds_twenty():
    """Class-action lens: death weight reduced from 50→20 in the 2026-05-09 rebalance.
    Severe individual harm pushes cases toward mass tort, not class certification."""
    assert compute_score(ClusterFacts(complaint_count=10, death_count=1)) == 30


def test_crash_adds_five():
    """Class-action lens: crash weight reduced from 10→5."""
    assert compute_score(ClusterFacts(complaint_count=10, crash_count=1)) == 15


def test_fire_adds_ten():
    """Class-action lens: fire weight reduced from 15→10."""
    assert compute_score(ClusterFacts(complaint_count=10, fire_count=1)) == 20


def test_severity_does_not_scale_with_count_only_presence():
    assert (
        compute_score(ClusterFacts(complaint_count=10, injury_count=1))
        == compute_score(ClusterFacts(complaint_count=10, injury_count=99))
    )


# ─── Optional signals ───────────────────────────────────────────────────

def test_multi_year_adds_twenty():
    """Class-action lens: multi-year (commonality) weight raised from 10→20."""
    assert compute_score(ClusterFacts(complaint_count=10, is_multi_year=True)) == 30


def test_open_investigation_adds_twenty_five():
    """Manufacturer-knowledge weight raised from 20→25 in the rebalance."""
    assert (
        compute_score(ClusterFacts(complaint_count=10, nhtsa_investigation_open=True))
        == 35
    )


def test_recall_adds_thirty():
    """Manufacturer-knowledge weight raised from 25→30 in the rebalance."""
    assert compute_score(ClusterFacts(complaint_count=10, recall_issued=True)) == 40


def test_existing_class_action_subtracts_thirty():
    assert (
        compute_score(ClusterFacts(complaint_count=10, class_action_filed=True)) == 0
    )


# ─── Lens-reframe archetypes (2026-05-09 rebalance) ─────────────────────

def test_class_action_archetype_outscores_mass_tort_archetype():
    """A widespread economic-harm cluster (high volume, multi-year, mfr knowledge,
    no severity) should now outscore a low-volume severe-injury cluster — that's
    the entire point of the class-action lens.
    """
    class_action_archetype = ClusterFacts(
        complaint_count=200,        # numerosity
        is_multi_year=True,         # commonality
        nhtsa_investigation_open=True,  # mfr knowledge
        # no deaths, no injuries, no recall yet
    )
    mass_tort_archetype = ClusterFacts(
        complaint_count=10,         # low volume — too small for a class
        injury_count=5,
        death_count=2,
        crash_count=3,
        fire_count=1,
        # single year, no investigation, no recall
    )
    class_action_score = compute_score(class_action_archetype)
    mass_tort_score = compute_score(mass_tort_archetype)
    assert class_action_score > mass_tort_score, (
        f"class-action archetype ({class_action_score}) should outscore "
        f"mass-tort archetype ({mass_tort_score}) under the new lens"
    )


def test_severe_low_volume_no_longer_dominates():
    """Pre-rebalance: 10 complaints + 1 death = 60 (WATCH). Post-rebalance: 30 (MONITOR).
    Captures the intentional shift away from death/injury dominance.
    """
    facts = ClusterFacts(complaint_count=10, death_count=1)
    score = compute_score(facts)
    assert score == 30
    # Confirm the classification dropped from WATCH (50+) to MONITOR (25-49).
    from signalwarn.scoring import classify
    assert classify(score) == "MONITOR"


def test_widespread_quiet_defect_now_actionable():
    """Pre-rebalance: 200 complaints + multi-year + investigation = 30+10+20 = 60 (WATCH).
    Post-rebalance: 50+20+25 = 95 (CRITICAL). The quiet-but-systemic class-action
    archetype now reaches CRITICAL without any death/injury signal.
    """
    facts = ClusterFacts(
        complaint_count=200,
        is_multi_year=True,
        nhtsa_investigation_open=True,
    )
    score = compute_score(facts)
    assert score == 95
    from signalwarn.scoring import classify
    assert classify(score) == "CRITICAL"


# ─── Bounds ─────────────────────────────────────────────────────────────

def test_score_never_exceeds_one_hundred():
    facts = ClusterFacts(
        complaint_count=500,
        velocity_30d=400,
        injury_count=10,
        death_count=10,
        crash_count=5,
        fire_count=5,
        is_multi_year=True,
        nhtsa_investigation_open=True,
        recall_issued=True,
    )
    assert compute_score(facts) == 100


def test_score_never_drops_below_zero():
    facts = ClusterFacts(complaint_count=1, class_action_filed=True)
    assert compute_score(facts) == 0


# ─── Classification thresholds ──────────────────────────────────────────

@pytest.mark.parametrize(
    "score,expected",
    [
        (0, "NOISE"),
        (24, "NOISE"),
        (25, "MONITOR"),
        (49, "MONITOR"),
        (50, "WATCH"),
        (69, "WATCH"),
        (70, "HOT"),
        (89, "HOT"),
        (90, "CRITICAL"),
        (100, "CRITICAL"),
    ],
)
def test_classification_thresholds(score: int, expected: str):
    assert classify(score) == expected
