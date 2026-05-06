"""Component normalization.

NHTSA components arrive as free-form strings (often a slash-separated list).
We map them to a small set of canonical categories per spec §6.3.
"""
from __future__ import annotations

# Order matters: longer/more specific phrases first so they win over substrings.
_RULES: list[tuple[tuple[str, ...], str]] = [
    (("AIR BAG", "AIRBAG"), "AIR BAGS"),
    (("SERVICE BRAKE", "BRAKE"), "BRAKES"),
    (("POWER TRAIN", "TRANSMISSION", "DRIVELINE"), "POWER TRAIN"),
    (("ENGINE",), "ENGINE"),
    (("STEERING",), "STEERING"),
    (("ELECTRICAL",), "ELECTRICAL"),
    (("FUEL",), "FUEL SYSTEM"),
    (("SUSPENSION",), "SUSPENSION"),
    (("TIRE",), "TIRES"),
    (("SEAT BELT",), "SEAT BELTS"),
    (("EXTERIOR LIGHTING", "LIGHTING"), "LIGHTING"),
    (("STRUCTURE",), "STRUCTURE"),
    (("VEHICLE SPEED CONTROL",), "SPEED CONTROL"),
    (("EXHAUST",), "EXHAUST"),
]


def normalize_component(raw: str | None) -> str:
    """Return the canonical component category for a raw NHTSA component string."""
    if not raw:
        return "OTHER"
    upper = raw.upper()
    for keywords, canonical in _RULES:
        if any(k in upper for k in keywords):
            return canonical
    return "OTHER"
