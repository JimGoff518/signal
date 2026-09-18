"""Pure-function tests for the dashboard query builders (no DB needed)."""
from __future__ import annotations

from datetime import date

from web import queries


def test_build_filters_defaults_hide_noise_and_terminated():
    where, params = queries._build_filters()
    assert "c.classification != 'NOISE'" in where
    assert "class_action_status" in where
    assert params == {}


def test_build_filters_component_recall_filed():
    where, params = queries._build_filters(
        component="engine", recall="1", filed="1"
    )
    assert "c.component = %(component)s" in where
    assert params["component"] == "ENGINE"
    assert "c.recall_issued = TRUE" in where
    assert "c.class_action_filed = TRUE" in where


def test_build_filters_not_filed_and_no_recall():
    where, _ = queries._build_filters(recall="0", filed="0")
    assert "c.recall_issued = FALSE" in where
    assert "c.class_action_filed = FALSE" in where


def test_build_filters_ignores_blank_tristate():
    where, params = queries._build_filters(recall="", filed=None, component="")
    assert "recall_issued" not in where
    assert "class_action_filed" not in where
    assert "component" not in params


def test_build_filters_activity_window_uses_today():
    where, params = queries._build_filters(activity_window_days=30)
    assert "c.last_complaint_date >= %(floor)s" in where
    assert (date.today() - params["floor"]).days == 30


def test_build_order_by_rejects_unknown_sort():
    assert queries._build_order_by("drop table", "asc").startswith("c.score")


def test_months_axis_exact_bucket_count_ending_this_month():
    axis = queries.months_axis(12)
    assert len(axis) == 12
    assert axis[-1] == date.today().replace(day=1)
    assert all(d.day == 1 for d in axis)
    assert axis == sorted(axis)
