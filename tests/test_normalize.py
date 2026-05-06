"""Tests for component normalization."""
from __future__ import annotations

import pytest

from signalwarn.normalize import normalize_component


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ENGINE AND ENGINE COOLING", "ENGINE"),
        ("ENGINE", "ENGINE"),
        ("POWER TRAIN", "POWER TRAIN"),
        ("TRANSMISSION", "POWER TRAIN"),
        ("DRIVELINE", "POWER TRAIN"),
        ("AIR BAGS", "AIR BAGS"),
        ("AIRBAG", "AIR BAGS"),
        ("SERVICE BRAKES, HYDRAULIC", "BRAKES"),
        ("BRAKES", "BRAKES"),
        ("STEERING", "STEERING"),
        ("ELECTRICAL SYSTEM", "ELECTRICAL"),
        ("FUEL SYSTEM, GASOLINE", "FUEL SYSTEM"),
        ("SUSPENSION", "SUSPENSION"),
        ("TIRES", "TIRES"),
        ("UNKNOWN OR OTHER", "OTHER"),
        ("", "OTHER"),
        (None, "OTHER"),
    ],
)
def test_normalize_component(raw, expected):
    assert normalize_component(raw) == expected


def test_normalization_is_case_insensitive():
    assert normalize_component("engine and engine cooling") == "ENGINE"
