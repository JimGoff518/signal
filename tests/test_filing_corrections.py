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


def test_williams_cvt_allowed_on_equinox_power_train_not_barba_trucks():
    williams = _filing(
        "Williams v. General Motors LLC — Malibu Trailblazer Equinox Terrain CVT"
    )
    # Intended CVT homes (tracked Equinox + untracked siblings if present).
    assert allowed_by_corrections(williams, "CHEVROLET", "EQUINOX", "POWER TRAIN")
    assert allowed_by_corrections(williams, "CHEVROLET", "MALIBU", "POWER TRAIN")
    assert allowed_by_corrections(williams, "CHEVROLET", "TRAILBLAZER", "POWER TRAIN")
    assert allowed_by_corrections(williams, "GMC", "TERRAIN", "POWER TRAIN")
    assert same_defect_override(williams) is True
    # Barba 8-speed truck/SUV surface — must NOT collapse Williams onto them.
    assert not allowed_by_corrections(williams, "CHEVROLET", "SILVERADO", "POWER TRAIN")
    assert not allowed_by_corrections(williams, "CHEVROLET", "SUBURBAN", "POWER TRAIN")
    assert not allowed_by_corrections(williams, "CHEVROLET", "TAHOE", "POWER TRAIN")
    assert not allowed_by_corrections(williams, "GMC", "YUKON", "POWER TRAIN")
    assert not allowed_by_corrections(williams, "GMC", "SIERRA", "POWER TRAIN")
    # Wrong component.
    assert not allowed_by_corrections(williams, "CHEVROLET", "EQUINOX", "BRAKES")


def test_barba_8speed_rejected_on_williams_cvt_models():
    barba = _filing("Matthew Barba v. General Motors LLC")
    assert allowed_by_corrections(barba, "CHEVROLET", "SILVERADO", "POWER TRAIN")
    assert allowed_by_corrections(barba, "CHEVROLET", "SUBURBAN", "POWER TRAIN")
    assert allowed_by_corrections(barba, "GMC", "SIERRA", "POWER TRAIN")
    # Williams CVT models — Barba must not attach here.
    assert not allowed_by_corrections(barba, "CHEVROLET", "EQUINOX", "POWER TRAIN")
    assert not allowed_by_corrections(barba, "CHEVROLET", "MALIBU", "POWER TRAIN")
    assert not allowed_by_corrections(barba, "GMC", "TERRAIN", "POWER TRAIN")
    assert same_defect_override(barba) is True


def test_williams_caption_model_conflict_rejects_suburban():
    williams = _filing(
        "Williams v. General Motors LLC (Equinox Malibu Trailblazer Terrain CVT)"
    )
    assert model_conflict(williams, "CHEVROLET", "SUBURBAN")
    assert not model_conflict(williams, "CHEVROLET", "EQUINOX")
    assert models_named_in_caption(williams.case_name) >= {
        "EQUINOX",
        "MALIBU",
        "TRAILBLAZER",
        "TERRAIN",
    }


def test_goldenkranz_iccu_allowed_on_ev_electrical_not_ice_hyundais():
    golden = _filing(
        "Goldenkranz v. Hyundai Motor America — Ioniq 5 ICCU 12V battery"
    )
    assert allowed_by_corrections(golden, "HYUNDAI", "IONIQ 5", "ELECTRICAL")
    assert allowed_by_corrections(golden, "HYUNDAI", "IONIQ 6", "ELECTRICAL")
    assert allowed_by_corrections(golden, "KIA", "EV6", "ELECTRICAL")
    assert allowed_by_corrections(golden, "KIA", "EV9", "ELECTRICAL")
    assert allowed_by_corrections(golden, "GENESIS", "GV60", "ELECTRICAL")
    assert same_defect_override(golden) is True
    # Currently tracked ICE/crossover Hyundais/Kias — must not false-attach.
    assert not allowed_by_corrections(golden, "HYUNDAI", "TUCSON", "ELECTRICAL")
    assert not allowed_by_corrections(golden, "HYUNDAI", "SANTA FE", "ELECTRICAL")
    assert not allowed_by_corrections(golden, "HYUNDAI", "ELANTRA", "ELECTRICAL")
    assert not allowed_by_corrections(golden, "KIA", "TELLURIDE", "ELECTRICAL")
    assert not allowed_by_corrections(golden, "KIA", "SORENTO", "ELECTRICAL")
    assert not allowed_by_corrections(golden, "HYUNDAI", "IONIQ 5", "POWER TRAIN")


def test_find_class_action_skips_williams_on_suburban(monkeypatch):
    class _Fake:
        def search(self, q, *, limit=5, **_):
            return [
                _filing(
                    "Williams v. General Motors LLC — Malibu Equinox Terrain CVT"
                )
            ]

    assert find_class_action(_Fake(), "CHEVROLET", "SUBURBAN", "POWER TRAIN") is None
    hit = find_class_action(_Fake(), "CHEVROLET", "EQUINOX", "POWER TRAIN")
    assert hit is not None and "Williams" in hit.case_name


def test_find_class_action_skips_goldenkranz_on_tucson(monkeypatch):
    class _Fake:
        def search(self, q, *, limit=5, **_):
            return [
                _filing(
                    "Goldenkranz v. Hyundai Motor America (Ioniq 5 ICCU)"
                )
            ]

    assert find_class_action(_Fake(), "HYUNDAI", "TUCSON", "ELECTRICAL") is None
    hit = find_class_action(_Fake(), "HYUNDAI", "IONIQ 5", "ELECTRICAL")
    assert hit is not None and "Goldenkranz" in hit.case_name


def test_thieme_still_ok_after_equinox_sibling_union():
    """Williams CVT sibling expansion must not break Thieme Equinox BRAKES."""
    thieme = _filing(
        "Thieme v. General Motors LLC — Equinox / Terrain / Envision Vacuum Pump"
    )
    assert allowed_by_corrections(thieme, "CHEVROLET", "EQUINOX", "BRAKES")
    assert not allowed_by_corrections(thieme, "CHEVROLET", "SUBURBAN", "BRAKES")


def test_cass_altima_ocs_allowed_on_altima_air_bags_not_rogue():
    cass = _filing(
        "Cass v. NISSAN NORTH AMERICA, INC",
        court="District Court, C.D. California",
    )
    assert allowed_by_corrections(cass, "NISSAN", "ALTIMA", "AIR BAGS")
    assert same_defect_override(cass) is True
    # Tracked Nissan siblings — must not false-attach.
    assert not allowed_by_corrections(cass, "NISSAN", "ROGUE", "AIR BAGS")
    assert not allowed_by_corrections(cass, "NISSAN", "FRONTIER", "AIR BAGS")
    # Wrong component on Altima.
    assert not allowed_by_corrections(cass, "NISSAN", "ALTIMA", "ELECTRICAL")
    assert not allowed_by_corrections(cass, "NISSAN", "ALTIMA", "POWER TRAIN")


def test_find_class_action_skips_cass_on_rogue(monkeypatch):
    class _Fake:
        def search(self, q, *, limit=5, **_):
            return [
                _filing(
                    "Cass v. NISSAN NORTH AMERICA, INC",
                    court="District Court, C.D. California",
                )
            ]

    assert find_class_action(_Fake(), "NISSAN", "ROGUE", "AIR BAGS") is None
    hit = find_class_action(_Fake(), "NISSAN", "ALTIMA", "AIR BAGS")
    assert hit is not None and "Cass" in hit.case_name


def test_models_named_in_caption_finds_altima():
    assert models_named_in_caption(
        "Cass et al. v. Nissan North America — 2016-2018 Altima OCS"
    ) >= {"ALTIMA"}


def test_fehrmann_brake_allowed_on_named_gm_brakes_only():
    fehrmann = _filing(
        "Fehrmann v. GENERAL MOTORS LLC",
        court="District Court, E.D. Pennsylvania",
    )
    # Tracked homes (Colorado / Canyon) plus untracked named models.
    assert allowed_by_corrections(fehrmann, "CHEVROLET", "COLORADO", "BRAKES")
    assert allowed_by_corrections(fehrmann, "GMC", "CANYON", "BRAKES")
    assert allowed_by_corrections(fehrmann, "CHEVROLET", "TRAVERSE", "BRAKES")
    assert allowed_by_corrections(fehrmann, "GMC", "ACADIA", "BRAKES")
    assert allowed_by_corrections(fehrmann, "BUICK", "ENCLAVE", "BRAKES")
    assert same_defect_override(fehrmann) is True
    # Other GM models with tracked BRAKES keys must not take it.
    assert not allowed_by_corrections(fehrmann, "CHEVROLET", "SILVERADO", "BRAKES")
    assert not allowed_by_corrections(fehrmann, "GMC", "SIERRA", "BRAKES")
    assert not allowed_by_corrections(fehrmann, "CHEVROLET", "EQUINOX", "BRAKES")
    assert not allowed_by_corrections(fehrmann, "CHEVROLET", "SUBURBAN", "BRAKES")
    assert not allowed_by_corrections(fehrmann, "GMC", "YUKON", "BRAKES")
    # Non-brake components on the right model.
    assert not allowed_by_corrections(fehrmann, "CHEVROLET", "COLORADO", "ENGINE")
    assert not allowed_by_corrections(fehrmann, "GMC", "CANYON", "POWER TRAIN")
    assert not allowed_by_corrections(fehrmann, "CHEVROLET", "COLORADO", "ELECTRICAL")
    # Wrong make.
    assert not allowed_by_corrections(fehrmann, "FORD", "RANGER", "BRAKES")


def test_find_class_action_skips_fehrmann_on_silverado_brakes(monkeypatch):
    class _Fake:
        def search(self, q, *, limit=5, **_):
            return [
                _filing(
                    "Fehrmann v. GENERAL MOTORS LLC",
                    court="District Court, E.D. Pennsylvania",
                )
            ]

    assert find_class_action(_Fake(), "CHEVROLET", "SILVERADO", "BRAKES") is None
    assert find_class_action(_Fake(), "CHEVROLET", "COLORADO", "ENGINE") is None
    hit = find_class_action(_Fake(), "CHEVROLET", "COLORADO", "BRAKES")
    assert hit is not None and "Fehrmann" in hit.case_name



# ─── Model-year guard (allow_years) ─────────────────────────────────────


def test_fehrmann_year_guard_rejects_2019_accepts_2025():
    fehrmann = _filing("Fehrmann v. GENERAL MOTORS LLC")
    assert not allowed_by_corrections(
        fehrmann, "CHEVROLET", "COLORADO", "BRAKES", model_year=2019
    )
    assert not allowed_by_corrections(
        fehrmann, "GMC", "CANYON", "BRAKES", model_year=2024
    )
    assert allowed_by_corrections(
        fehrmann, "CHEVROLET", "COLORADO", "BRAKES", model_year=2025
    )
    assert allowed_by_corrections(fehrmann, "GMC", "CANYON", "BRAKES", model_year=2025)
    # Right year does not rescue a wrong model or component.
    assert not allowed_by_corrections(
        fehrmann, "CHEVROLET", "SILVERADO", "BRAKES", model_year=2025
    )
    assert not allowed_by_corrections(
        fehrmann, "CHEVROLET", "COLORADO", "ENGINE", model_year=2025
    )


def test_cass_year_guard_rejects_2014_accepts_2017():
    cass = _filing(
        "Cass v. NISSAN NORTH AMERICA, INC",
        court="District Court, C.D. California",
    )
    assert not allowed_by_corrections(cass, "NISSAN", "ALTIMA", "AIR BAGS", model_year=2014)
    assert not allowed_by_corrections(cass, "NISSAN", "ALTIMA", "AIR BAGS", model_year=2019)
    assert allowed_by_corrections(cass, "NISSAN", "ALTIMA", "AIR BAGS", model_year=2017)
    assert allowed_by_corrections(cass, "NISSAN", "ALTIMA", "AIR BAGS", model_year=2016)
    assert allowed_by_corrections(cass, "NISSAN", "ALTIMA", "AIR BAGS", model_year=2018)


def test_all_years_key_attaches_vehicle_only_when_rule_has_allow_years():
    fehrmann = _filing("Fehrmann v. GENERAL MOTORS LLC")
    cass = _filing("Cass v. NISSAN NORTH AMERICA, INC")
    # ALL_YEARS aggregate (model_year None) is not rejected by the year guard.
    assert allowed_by_corrections(fehrmann, "CHEVROLET", "COLORADO", "BRAKES")
    assert allowed_by_corrections(cass, "NISSAN", "ALTIMA", "AIR BAGS", model_year=None)
    # But it goes vehicle-only.
    assert same_defect_override(fehrmann, all_years=True) is False
    assert same_defect_override(cass, all_years=True) is False
    # Per-year keys keep the forced same_defect.
    assert same_defect_override(fehrmann) is True
    assert same_defect_override(cass, all_years=False) is True


def test_rules_without_allow_years_unchanged_on_all_years_keys():
    thieme = _filing("Thieme v. General Motors LLC (Equinox Vacuum Pump)")
    petro = _filing("Petro v. FCA US LLC (HEMI Engine)")
    assert allowed_by_corrections(thieme, "CHEVROLET", "EQUINOX", "BRAKES", model_year=2012)
    assert same_defect_override(thieme, all_years=True) is True
    assert same_defect_override(petro, all_years=True) is True


def test_find_class_action_year_guard_skips_to_next_hit():
    """A wrong-year Fehrmann hit is skipped like a wrong-model hit, so the
    next plausible filing in the results can still attach."""

    other = _filing("Smith v. General Motors LLC (Colorado brake booster)")

    class _Fake:
        def search(self, q, *, limit=5, **_):
            return [_filing("Fehrmann v. GENERAL MOTORS LLC"), other]

    hit_2019 = find_class_action(
        _Fake(), "CHEVROLET", "COLORADO", "BRAKES", model_year=2019
    )
    assert hit_2019 is not None and "Smith" in hit_2019.case_name
    hit_2025 = find_class_action(
        _Fake(), "CHEVROLET", "COLORADO", "BRAKES", model_year=2025
    )
    assert hit_2025 is not None and "Fehrmann" in hit_2025.case_name
    hit_all = find_class_action(_Fake(), "CHEVROLET", "COLORADO", "BRAKES")
    assert hit_all is not None and "Fehrmann" in hit_all.case_name


def test_run_check_filings_plumbs_model_year_and_all_years(monkeypatch):
    """SELECT now carries model_year / is_multi_year; the loop passes them on."""
    import signalwarn.filings_check as fc

    rows = [
        {"id": 1, "make": "CHEVROLET", "model": "COLORADO", "model_year": 2019,
         "is_multi_year": False, "component": "BRAKES",
         "classification": "SIGNAL", "score": 90},
        {"id": 2, "make": "CHEVROLET", "model": "COLORADO", "model_year": 2025,
         "is_multi_year": False, "component": "BRAKES",
         "classification": "SIGNAL", "score": 80},
        {"id": 3, "make": "CHEVROLET", "model": "COLORADO", "model_year": None,
         "is_multi_year": True, "component": "BRAKES",
         "classification": "SIGNAL", "score": 70},
    ]
    seen_sql: list[str] = []

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            seen_sql.append(sql)

        def fetchall(self):
            return list(rows)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def search(self, q, *, limit=5, **_):
            return [_filing("Fehrmann v. GENERAL MOTORS LLC")]

    marked: dict[int, tuple] = {}

    def _fake_mark(cluster_id, *, filing, same_defect, status=None, dry_run=False):
        marked[cluster_id] = (filing.case_name if filing else None, same_defect)

    monkeypatch.setattr(fc, "connection", lambda: _Conn())
    monkeypatch.setattr(fc, "CourtListenerClient", _Client)
    monkeypatch.setattr(fc, "_mark_checked", _fake_mark)

    summary = fc.run_check_filings(dry_run=True)
    assert "model_year" in seen_sql[0] and "is_multi_year" in seen_sql[0]
    assert summary["matched"] == 2
    # 2019: rejected by the year guard, treated as no match.
    assert marked[1] == (None, False)
    # 2025: same defect.
    assert marked[2][0].startswith("Fehrmann") and marked[2][1] is True
    # ALL_YEARS: attaches, vehicle-only.
    assert marked[3][0].startswith("Fehrmann") and marked[3][1] is False
