"""Tests for the 0-100 scoring engine and classifier."""
from __future__ import annotations

import pytest

from signalwarn.scoring import ClusterFacts, classify, compute_score


# ─── Base score (volume) ────────────────────────────────────────────────

def test_empty_cluster_scores_zero():
    assert compute_score(ClusterFacts()) == 0


def test_volume_under_cap_contributes_one_per_complaint():
    assert compute_score(ClusterFacts(complaint_count=10)) == 10


def test_volume_caps_at_thirty():
    assert compute_score(ClusterFacts(complaint_count=500)) == 30


# ─── Velocity multipliers ───────────────────────────────────────────────

def test_velocity_doubled_applies_2x_to_base():
    facts = ClusterFacts(complaint_count=30, velocity_30d=15)  # 50% in last 30d
    assert compute_score(facts) == 60


def test_velocity_tripled_applies_3x_to_base():
    facts = ClusterFacts(complaint_count=30, velocity_30d=20)  # 66.7%
    assert compute_score(facts) == 90


def test_velocity_zero_applies_no_multiplier():
    facts = ClusterFacts(complaint_count=30, velocity_30d=0)
    assert compute_score(facts) == 30


def test_velocity_below_doubled_threshold_applies_no_multiplier():
    facts = ClusterFacts(complaint_count=30, velocity_30d=10)  # 33%
    assert compute_score(facts) == 30


# ─── Severity escalators ────────────────────────────────────────────────

def test_injury_adds_twenty():
    assert compute_score(ClusterFacts(complaint_count=10, injury_count=1)) == 30


def test_death_adds_fifty():
    assert compute_score(ClusterFacts(complaint_count=10, death_count=1)) == 60


def test_crash_adds_ten():
    assert compute_score(ClusterFacts(complaint_count=10, crash_count=1)) == 20


def test_fire_adds_fifteen():
    assert compute_score(ClusterFacts(complaint_count=10, fire_count=1)) == 25


def test_severity_does_not_scale_with_count_only_presence():
    assert (
        compute_score(ClusterFacts(complaint_count=10, injury_count=1))
        == compute_score(ClusterFacts(complaint_count=10, injury_count=99))
    )


# ─── Optional signals ───────────────────────────────────────────────────

def test_multi_year_adds_ten():
    assert compute_score(ClusterFacts(complaint_count=10, is_multi_year=True)) == 20


def test_open_investigation_adds_twenty():
    assert (
        compute_score(ClusterFacts(complaint_count=10, nhtsa_investigation_open=True))
        == 30
    )


def test_recall_adds_twenty_five():
    assert compute_score(ClusterFacts(complaint_count=10, recall_issued=True)) == 35


def test_existing_class_action_subtracts_thirty():
    assert (
        compute_score(ClusterFacts(complaint_count=10, class_action_filed=True)) == 0
    )


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
