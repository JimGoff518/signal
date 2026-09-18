"""Pure geometry for the dashboard's inline-SVG charts.

No DB, no templates — takes plain numbers and returns coordinates / path
strings that the Jinja templates drop straight into <svg>. Keeping this in
Python (rather than a JS chart library) means the charts are server-rendered,
have no runtime dependency, and are unit-testable.
"""
from __future__ import annotations

import math
from typing import Any

# Multipliers of the decade that count as "clean" axis maxima.
_NICE_STEPS = (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)


def nice_max(value: float) -> float:
    """Round `value` up to a clean axis ceiling (7 -> 8, 123 -> 150, 1234 -> 1500).

    Never returns 0 so callers can divide by it.
    """
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    for step in _NICE_STEPS:
        candidate = step * magnitude
        if candidate >= value:
            return int(candidate) if float(candidate).is_integer() else candidate
    return 10 * magnitude  # unreachable: step 10 always satisfies


def y_ticks(y_max: float, n: int = 3) -> list[float]:
    """`n` evenly spaced ticks from 0 to `y_max`, inclusive of both ends."""
    step = y_max / n
    ticks = [round(step * i, 6) for i in range(n + 1)]
    return [int(t) if float(t).is_integer() else t for t in ticks]


def _round1(v: float) -> str:
    """Format with at most one decimal — keeps SVG path strings short."""
    r = round(v, 1)
    return str(int(r)) if r == int(r) else f"{r:.1f}"


def scale_points(
    values: list[float],
    *,
    width: float,
    height: float,
    y_max: float,
    pad_x: float = 0,
    pad_y: float = 0,
) -> list[tuple[float, float]]:
    """Map a series onto an SVG box. x spreads evenly across the padded width;
    y=0 sits on the bottom edge (height - pad_y) and y_max on the top edge."""
    if not values:
        return []
    inner_w = width - 2 * pad_x
    inner_h = height - 2 * pad_y
    n = len(values)
    y_max = y_max or 1
    out: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        x = pad_x + (inner_w / 2 if n == 1 else inner_w * i / (n - 1))
        y = pad_y + inner_h - (inner_h * v / y_max)
        out.append((float(x), float(y)))
    return out


def line_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    parts = [f"M{_round1(points[0][0])},{_round1(points[0][1])}"]
    parts += [f"L{_round1(x)},{_round1(y)}" for x, y in points[1:]]
    return " ".join(parts)


def area_path(points: list[tuple[float, float]], *, baseline_y: float) -> str:
    """Line path closed down to the baseline — the ~10% wash under a line."""
    if not points:
        return ""
    last_x = points[-1][0]
    first_x = points[0][0]
    return (
        f"{line_path(points)} L{_round1(last_x)},{_round1(baseline_y)} "
        f"L{_round1(first_x)},{_round1(baseline_y)} Z"
    )


def hbar_layout(rows: list[dict[str, Any]], *, max_width: float) -> list[dict[str, Any]]:
    """Horizontal-bar widths proportional to the largest `n` in `rows`.

    Returns [{label, n, width, share}] in the input order (already sorted by
    the query). `share` is n / max, handy for direct labels.
    """
    if not rows:
        return []
    top = max(int(r["n"]) for r in rows) or 1
    out = []
    for r in rows:
        n = int(r["n"])
        share = n / top
        out.append(
            {"label": r["label"], "n": n, "width": round(max_width * share, 1), "share": share}
        )
    return out
