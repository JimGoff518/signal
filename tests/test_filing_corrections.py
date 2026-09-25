"""Unit tests for curated Scout P0 CourtListener match corrections."""
from __future__ import annotations

from datetime import date

from signalwarn.courtlistener import Filing, find_class_action
from signalwarn.filing_corrections import (
    allowed_by_corrections,
    model_conflict,
    models_named_in_caption,
    same_defect_override,
    status_override,
)


def _filing(name: str, court: str = "District Court, E.D. Michigan") -> Filing:
    return Filing(
        case_name=name,
        court=court,
        date_filed=date(2024, 1, 1),
        docket_number="1:24-cv-00001",
        absolute_url="/docket/1/",
    )


def test_models_named_in_caption_finds_gm_crossovers():
    assert models_named_in_caption(
        "Thieme v. General Motors LLC (Equinox Terrain Envision Vacuum Pump)"
    ) >= {"EQUINOX", "TERRAIN", "ENVISION"}


def test_thieme_rejected_for_suburban_and_yukon_brakes():
    thieme = _filing(
        "Thieme v. General Motors LLC — Equinox / Terrain / Envision Vacuum Pump"
    )
    assert model_conflict(thieme, "CHEVROLET", "SUBURBAN")
    assert model_conflict(thieme, "GMC", "YUKON")
    assert not allowed_by_corrections(thieme, "CHEVROLET", "SUBURBAN", "BRAKES")
    assert not allowed_by_corrections(thieme, "GMC", "YUKON", "BRAKES")
    # Correct home: Chevy Equinox BRAKES.
    assert allowed_by_corrections(thieme, "CHEVROLET", "EQUINOX", "BRAKES")
    assert same_defect_override(thieme) is True


def test_norberg_does_not_same_defect_collapse_into_petro_hemi_track():
    norberg = _filing("Norberg et al. v. FCA US LLC (Hurricane ECM)")
    assert allowed_by_corrections(norberg, "RAM", "1500", "ENGINE")
    # Forced False so Petro HEMI remains a distinct opportunity surface on the
    # shared RAM::1500::*::ENGINE key until sub-defect clustering exists.
    assert same_defect_override(norberg) is False


def test_petro_hemi_stays_same_defect_on_ram_1500_engine():
    petro = _filing("Petro v. FCA US LLC (HEMI Engine)")
    assert allowed_by_corrections(petro, "RAM", "1500", "ENGINE")
    assert same_defect_override(petro) is True


def test_oconnor_status_override_is_cert_denied():
    oconnor = _filing(
        "O'Connor v. Ford Motor Company",
        court="District Court, N.D. Illinois",
    )
    assert allowed_by_corrections(oconnor, "FORD", "F-150", "POWER TRAIN")
    assert status_override(oconnor) == "cert_denied"
    assert same_defect_override(oconnor) is True
    # Wrong vehicle / component rejected.
    assert not allowed_by_corrections(oconnor, "FORD", "EXPLORER", "POWER TRAIN")
    assert not allowed_by_corrections(oconnor, "FORD", "F-150", "ENGINE")


def test_find_class_action_skips_thieme_on_suburban(monkeypatch):
    """Corrections layer must filter inside find_class_action, not only at write."""

    class _Fake:
        def search(self, q, *, limit=5, **_):
            return [
                _filing(
                    "Thieme v. General Motors LLC — Equinox Terrain Envision Vacuum Pump"
                )
            ]

    assert find_class_action(_Fake(), "CHEVROLET", "SUBURBAN", "BRAKES") is None
    hit = find_class_action(_Fake(), "CHEVROLET", "EQUINOX", "BRAKES")
    assert hit is not None and "Thieme" in hit.case_name
