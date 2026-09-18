"""Geometry helpers that turn query rows into inline-SVG coordinates."""
from __future__ import annotations

import pytest

from web import charts


@pytest.mark.parametrize(
    "value, expected",
    [(0, 1), (1, 1), (7, 8), (10, 10), (11, 15), (123, 150), (1234, 1500), (4800, 5000)],
)
def test_nice_max_rounds_up_to_clean_number(value, expected):
    assert charts.nice_max(value) == expected


def test_y_ticks_are_evenly_spaced_and_include_top():
    assert charts.y_ticks(150, n=3) == [0, 50, 100, 150]


def test_scale_points_maps_into_plot_box():
    pts = charts.scale_points([0, 5, 10], width=100, height=50, y_max=10, pad_x=10, pad_y=5)
    assert pts[0] == (10.0, 45.0)      # first value at left edge, zero on baseline
    assert pts[-1] == (90.0, 5.0)      # last value at right edge, max at top
    assert pts[1][1] == 25.0           # midpoint value halfway down


def test_scale_points_single_value_centers():
    pts = charts.scale_points([3], width=100, height=50, y_max=3, pad_x=10, pad_y=5)
    assert pts == [(50.0, 5.0)]


def test_line_and_area_paths():
    pts = [(0.0, 10.0), (10.0, 0.0)]
    assert charts.line_path(pts) == "M0,10 L10,0"
    assert charts.area_path(pts, baseline_y=20.0) == "M0,10 L10,0 L10,20 L0,20 Z"


def test_paths_use_one_decimal_precision():
    assert charts.line_path([(1.23456, 2.98765)]) == "M1.2,3"


def test_bar_widths_scale_to_max_and_cap_min_visible():
    rows = [{"label": "ENGINE", "n": 40}, {"label": "BRAKES", "n": 10}, {"label": "OTHER", "n": 0}]
    bars = charts.hbar_layout(rows, max_width=200)
    assert [b["width"] for b in bars] == [200.0, 50.0, 0.0]
    assert bars[0]["label"] == "ENGINE"
    assert bars[0]["share"] == 1.0


def test_hbar_layout_empty_is_empty():
    assert charts.hbar_layout([], max_width=200) == []
