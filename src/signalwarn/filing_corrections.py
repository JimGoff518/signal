"""Curated CourtListener match corrections for known Scout P0 watches.

CourtListener attaches at most one filing per (make, model, component) via
first-plausible-hit. That collapses distinct defect tracks (Norberg Hurricane
ECM vs Petro HEMI on the same RAM 1500 ENGINE key) and can pin a suit about
model A onto model B of the same manufacturer (Thieme vacuum-pump on
Suburban/Yukon BRAKES). Status is only pending|terminated from
dateTerminated, so a live docket with a denied certification (O'Connor)
still looks like an open cert path.

These rules are the mapping layer for cases Searcher/Scout have already
disambiguated. They filter and annotate hits inside find_class_action /
filings_check. Sub-defect cluster keys or multi-filing support would be a
separate, Jimmy-signed schema change — see the P0 GitHub issue.

Williams (VT40/TR690 CVT) and Barba (GM 8-speed) both land on POWER TRAIN
for GM makes; allow-lists keep them on disjoint model sets. Goldenkranz
(ICCU) is Hyundai/Kia/Genesis EV electrical — most named models are not
yet in TRACKED_VEHICLES (document gaps; do not invent tracks here). Cass
(Altima passenger OCS/airbag) pins NISSAN ALTIMA AIR BAGS only — reject
Rogue/Frontier false-attach.

Fehrmann (2025 GM master brake cylinder) pins BRAKES on the named GM
models only. Hubof (Duramax oil cooler) pins ENGINE on Silverado/Sierra
HD names; the base SILVERADO/SIERRA keys cannot separate HD from 1500, so
same_defect is False. Heikkila (BMW A/C evaporator) has no A/C bucket:
those complaints normalize to OTHER (sometimes ELECTRICAL), so it attaches
vehicle-only. BMW is not in TRACKED_VEHICLES.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from signalwarn.courtlistener import Filing

# Models that share a defect track. If a caption names a model outside the
# cluster model's sibling set (but still in our known-model list), reject.
# Keys/values are uppercase as stored on clusters.make / clusters.model.
MODEL_SIBLINGS: dict[str, dict[str, frozenset[str]]] = {
    "CHEVROLET": {
        # Equinox siblings union Thieme (Envision) + Williams CVT
        # (Malibu/Trailblazer/Terrain). Truck/SUV 8-speed (Barba) stays
        # on Suburban/Tahoe/Silverado/Colorado families.
        "EQUINOX": frozenset(
            {"EQUINOX", "TERRAIN", "ENVISION", "MALIBU", "TRAILBLAZER"}
        ),
        "MALIBU": frozenset({"MALIBU", "TRAILBLAZER", "EQUINOX", "TERRAIN"}),
        "TRAILBLAZER": frozenset(
            {"MALIBU", "TRAILBLAZER", "EQUINOX", "TERRAIN"}
        ),
        "SUBURBAN": frozenset({"SUBURBAN", "TAHOE", "YUKON"}),
        "TAHOE": frozenset({"SUBURBAN", "TAHOE", "YUKON"}),
        "SILVERADO": frozenset({"SILVERADO", "SIERRA"}),
        "COLORADO": frozenset({"COLORADO", "CANYON"}),
    },
    "GMC": {
        "YUKON": frozenset({"YUKON", "SUBURBAN", "TAHOE"}),
        "SIERRA": frozenset({"SIERRA", "SILVERADO"}),
        "CANYON": frozenset({"CANYON", "COLORADO"}),
        "TERRAIN": frozenset(
            {"TERRAIN", "EQUINOX", "ENVISION", "MALIBU", "TRAILBLAZER"}
        ),
    },
    "BUICK": {
        "ENVISION": frozenset({"ENVISION", "EQUINOX", "TERRAIN"}),
    },
    "HYUNDAI": {
        "IONIQ 5": frozenset({"IONIQ 5", "IONIQ 6", "IONIQ 9", "IONIQ"}),
        "IONIQ 6": frozenset({"IONIQ 5", "IONIQ 6", "IONIQ 9", "IONIQ"}),
        "IONIQ 9": frozenset({"IONIQ 5", "IONIQ 6", "IONIQ 9", "IONIQ"}),
        "IONIQ": frozenset({"IONIQ 5", "IONIQ 6", "IONIQ 9", "IONIQ"}),
    },
    "KIA": {
        "EV6": frozenset({"EV6", "EV9"}),
        "EV9": frozenset({"EV6", "EV9"}),
    },
    "GENESIS": {
        "GV60": frozenset({"GV60", "GV70", "GV80"}),
        "GV70": frozenset({"GV60", "GV70", "GV80"}),
        "GV80": frozenset({"GV60", "GV70", "GV80"}),
    },
    "NISSAN": {
        "ALTIMA": frozenset({"ALTIMA"}),
    },
    "RAM": {
        "1500": frozenset({"1500"}),
        "2500": frozenset({"2500", "3500"}),
        "3500": frozenset({"2500", "3500"}),
    },
    "FORD": {
        "F-150": frozenset({"F-150"}),
        "F-250": frozenset({"F-250", "F-350"}),
        "F-350": frozenset({"F-250", "F-350"}),
    },
}

# Caption tokens (lowercase) → uppercase model id. Longer phrases first.
_MODEL_CAPTION_TOKENS: tuple[tuple[str, str], ...] = (
    ("grand cherokee", "GRAND CHEROKEE"),
    ("f-150", "F-150"),
    ("f-250", "F-250"),
    ("f-350", "F-350"),
    ("trailblazer", "TRAILBLAZER"),
    ("silverado", "SILVERADO"),
    ("suburban", "SUBURBAN"),
    ("colorado", "COLORADO"),
    ("equinox", "EQUINOX"),
    ("envision", "ENVISION"),
    ("terrain", "TERRAIN"),
    ("malibu", "MALIBU"),
    ("yukon", "YUKON"),
    ("tahoe", "TAHOE"),
    ("sierra", "SIERRA"),
    ("canyon", "CANYON"),
    ("altima", "ALTIMA"),
    # Hyundai / Kia / Genesis EV tokens (Goldenkranz ICCU). Longer first.
    ("ioniq 5", "IONIQ 5"),
    ("ioniq 6", "IONIQ 6"),
    ("ioniq 9", "IONIQ 9"),
    ("ioniq", "IONIQ"),
    ("ev6", "EV6"),
    ("ev9", "EV9"),
    ("gv60", "GV60"),
    ("gv70", "GV70"),
    ("gv80", "GV80"),
)


@dataclass(frozen=True)
class CaptionRule:
    """If the caption matches, constrain which clusters may accept the hit."""

    id: str
    match_any: tuple[str, ...]  # lowercase substrings
    # One make, or several when one caption spans brands (Goldenkranz).
    allow_make: str | frozenset[str]
    allow_models: frozenset[str] | None  # None = any model of make
    allow_components: frozenset[str] | None  # None = any component
    status_override: str | None = None
    # When set, force class_action_same_defect rather than names_defect().
    same_defect: bool | None = None
    deny_all: bool = False
    note: str = ""

    def allowed_makes(self) -> frozenset[str]:
        if isinstance(self.allow_make, str):
            return frozenset({self.allow_make.upper()})
        return frozenset(m.upper() for m in self.allow_make)


# Scout watches: Norberg/Petro/Thieme/O'Connor (PR #4); Williams CVT /
# Barba 8-speed / Goldenkranz ICCU (PR #5); Cass Altima OCS (PR #14);
# Fehrmann GM brake / Hubof Duramax oil cooler / Heikkila BMW A/C.
CAPTION_RULES: tuple[CaptionRule, ...] = (
    CaptionRule(
        id="norberg_hurricane_ecm",
        match_any=("norberg",),
        allow_make="RAM",
        allow_models=frozenset({"1500"}),
        allow_components=frozenset({"ENGINE", "ELECTRICAL"}),
        # Hurricane ECM is its own track. Force same_defect False so a Norberg
        # hit does not hide / collapse the Petro HEMI ENGINE opportunity on the
        # shared RAM::1500::*::ENGINE key.
        same_defect=False,
        note=(
            "Norberg (E.D. Mich. 2:26-cv-13040) is Hurricane ECM — SEPARATE "
            "from Petro HEMI on RAM 1500 ENGINE. same_defect forced False so "
            "Signal does not collapse the Petro track into Norberg."
        ),
    ),
    CaptionRule(
        id="petro_hemi",
        match_any=("petro",),
        allow_make="RAM",
        allow_models=frozenset({"1500"}),
        allow_components=frozenset({"ENGINE"}),
        same_defect=True,
        note=(
            "Petro HEMI engine track on RAM 1500 ENGINE — distinct from "
            "Norberg Hurricane ECM."
        ),
    ),
    CaptionRule(
        id="thieme_vacuum_pump",
        match_any=("thieme",),
        allow_make="CHEVROLET",
        allow_models=frozenset({"EQUINOX"}),
        allow_components=frozenset({"BRAKES"}),
        same_defect=True,
        note=(
            "Thieme vacuum-pump suit is Equinox / Terrain / Envision — NOT "
            "Suburban / Yukon BRAKES. Sibling map + this allow-list reject "
            "Suburban/Yukon attachments."
        ),
    ),
    CaptionRule(
        id="oconnor_10r80_cert_denied",
        match_any=("o'connor", "o\u2019connor", "oconnor"),
        allow_make="FORD",
        allow_models=frozenset({"F-150"}),
        allow_components=frozenset({"POWER TRAIN"}),
        status_override="cert_denied",
        same_defect=True,
        note=(
            "O'Connor v. Ford (N.D. Ill. 1:19-cv-05045), 10R80 transmission: "
            "class certification DENIED Sep 14 2026. Flag cert_denied so "
            "Signal does not treat this as an open cert path."
        ),
    ),
    CaptionRule(
        id="williams_gm_cvt",
        match_any=("williams",),
        allow_make=frozenset({"CHEVROLET", "GMC"}),
        allow_models=frozenset({"MALIBU", "TRAILBLAZER", "EQUINOX", "TERRAIN"}),
        allow_components=frozenset({"POWER TRAIN", "TRANSMISSION"}),
        same_defect=True,
        note=(
            "Williams v. GM (D. Del. 1:26-cv-01162, filed 2026-09-15) — "
            "VT40/TR690 CVT on Malibu / Trailblazer / Equinox / Terrain. "
            "SEPARATE from Barba GM 8-speed; reject truck/SUV POWER TRAIN."
        ),
    ),
    CaptionRule(
        id="barba_gm_8speed",
        match_any=("barba",),
        allow_make=frozenset({"CHEVROLET", "GMC"}),
        # Tracked truck/SUV POWER TRAIN surface for GM 8-speed. Explicitly
        # excludes Williams CVT models (Equinox/Terrain/Malibu/Trailblazer).
        allow_models=frozenset(
            {
                "SILVERADO",
                "SIERRA",
                "TAHOE",
                "SUBURBAN",
                "YUKON",
                "COLORADO",
                "CANYON",
            }
        ),
        allow_components=frozenset({"POWER TRAIN", "TRANSMISSION"}),
        same_defect=True,
        note=(
            "Barba v. GM — GM 8-speed track on truck/SUV POWER TRAIN. "
            "SEPARATE from Williams VT40/TR690 CVT (Equinox/Terrain/Malibu/"
            "Trailblazer). Confirm live caption/models on re-check."
        ),
    ),
    CaptionRule(
        id="goldenkranz_iccu",
        match_any=("goldenkranz",),
        allow_make=frozenset({"HYUNDAI", "KIA", "GENESIS"}),
        allow_models=frozenset(
            {
                "IONIQ 5",
                "IONIQ 6",
                "IONIQ 9",
                "IONIQ",
                "EV6",
                "EV9",
                "GV60",
                "GV70",
                "GV80",
            }
        ),
        allow_components=frozenset({"ELECTRICAL"}),
        same_defect=True,
        note=(
            "Goldenkranz v. Hyundai Motor America (W.D. Wash. 2:26-cv-03581, "
            "filed 2026-09-23) — twice-recalled ICCU / 12V drain / loss of "
            "drive on Ioniq 5/6/9, EV6/EV9, Genesis GV60/GV70/GV80 EVs. "
            "Reject Tucson/Santa Fe/Elantra/Telluride/etc. Related older "
            "Young v. Hyundai Kefico (D.N.J. 3:26-cv-04198) is NOT this rule. "
            "Most named models are NOT in TRACKED_VEHICLES yet."
        ),
    ),
    CaptionRule(
        id="cass_nissan_altima_ocs",
        match_any=("cass",),
        allow_make="NISSAN",
        allow_models=frozenset({"ALTIMA"}),
        allow_components=frozenset({"AIR BAGS"}),
        same_defect=True,
        note=(
            "Cass v. Nissan North America (C.D. Cal. 5:26-cv-05613, filed "
            "2026-09-23; CL docket 74842719) — 2016–2018 Altima passenger "
            "occupant classification sensor (OCS) / airbag. Attach only to "
            "NISSAN::ALTIMA::*::AIR BAGS. Reject Rogue/Frontier and non-airbag "
            "components. Caption rarely names airbag, so same_defect forced "
            "True for this Scout-verified track."
        ),
    ),
    CaptionRule(
        id="fehrmann_gm_master_brake_cylinder",
        match_any=("fehrmann",),
        allow_make=frozenset({"CHEVROLET", "GMC", "BUICK"}),
        allow_models=frozenset(
            {
                "TRAVERSE",
                "ACADIA",
                "ENCLAVE",
                "COLORADO",
                "COLORADO ZR2 BISON",
                "CANYON",
                "CANYON AT4X AEV",
            }
        ),
        allow_components=frozenset({"BRAKES"}),
        same_defect=True,
        note=(
            "Fehrmann v. General Motors LLC (E.D. Pa. 2:26-cv-07669, filed "
            "2026-10-06; CL docket 74924532). 2025 Traverse / Acadia / "
            "Enclave / Colorado / Canyon master brake cylinder, loss of "
            "braking. Attach only to BRAKES on those models. Reject Silverado/"
            "Sierra/Tahoe/Equinox and non-brake components. Traverse, Acadia "
            "and Enclave are NOT in TRACKED_VEHICLES (BUICK is not tracked at "
            "all). Colorado/Canyon are tracked but 2025 clusters may not exist "
            "yet: recheck after #16. No model-year gate, so older Colorado/"
            "Canyon BRAKES keys also accept this hit."
        ),
    ),
    CaptionRule(
        id="hubof_gm_duramax_oil_cooler",
        match_any=("hubof",),
        allow_make=frozenset({"CHEVROLET", "GMC"}),
        # Base names (what MODEL_SIBLINGS and earlier rules use) plus the HD
        # model strings NHTSA reports for 2024-2026. 1500 and EV names are
        # left out on purpose.
        allow_models=frozenset(
            {
                "SILVERADO",
                "SILVERADO 2500",
                "SILVERADO 2500 ICE",
                "SILVERADO 2500HD",
                "SILVERADO 2500 HD",
                "SILVERADO 3500",
                "SILVERADO 3500HD",
                "SILVERADO 3500 HD",
                "SIERRA",
                "SIERRA HD",
                "SIERRA 2500",
                "SIERRA 2500 ICE",
                "SIERRA 2500HD",
                "SIERRA 2500 HD",
                "SIERRA 3500",
                "SIERRA 3500HD",
                "SIERRA 3500 HD",
            }
        ),
        # Oil cooler complaints file as "ENGINE AND ENGINE COOLING" -> ENGINE.
        allow_components=frozenset({"ENGINE"}),
        # A base SILVERADO / SIERRA ENGINE key mixes 1500 (6.2L L87) with
        # HD. Force False so Hubof does not hide the 1500 engine track.
        same_defect=False,
        note=(
            "Hubof v. General Motors, LLC (E.D. Mich. 2:26-cv-13622, filed "
            "2026-09-24; CL docket 74843881). 2024-2026 Silverado / Sierra "
            "2500HD/3500HD 6.6L Duramax cracked oil cooler. Attach only to "
            "ENGINE on Silverado/Sierra HD names. Reject 1500, EV, Colorado/"
            "Canyon and non-engine components. Base SILVERADO/SIERRA keys "
            "cannot tell HD from 1500, so same_defect forced False. Model "
            "year 2026 is outside MODEL_YEARS; 2024-2025 clusters: recheck "
            "after #16."
        ),
    ),
    CaptionRule(
        id="heikkila_bmw_ac_evaporator",
        match_any=("heikkila",),
        allow_make="BMW",
        # G-chassis families as NHTSA names them (2018-2025). F-chassis
        # X1 / X2 / 2 Series Gran Coupe / i3 and motorcycles are left out.
        allow_models=frozenset(
            {
                "2 SERIES COUPE",
                "M240I",
                "3 SERIES",
                "3 SERIES SEDAN",
                "3 SERIES HYBRID SEDAN",
                "330E",
                "M340I",
                "M3",
                "4 SERIES",
                "4 SERIES COUPE",
                "4 SERIES CONVERTIBLE",
                "4 SERIES GRAN COUPE",
                "430I",
                "430I XDRIVE",
                "M440I",
                "M4",
                "M4 COUPE",
                "M4 CONVERTIBLE",
                "I4",
                "I4 GRAN COUPE",
                "I4 EDRIVE40",
                "I4 XDRIVE40",
                "5 SERIES",
                "5 SERIES PHEV",
                "5 SERIES HYBRID SEDAN",
                "530I",
                "530E",
                "540I",
                "M550I",
                "M5",
                "I5",
                "6 SERIES",
                "7 SERIES",
                "7 SERIES SEDAN",
                "7 SERIES PHEV",
                "7 SERIES HYBRID SEDAN",
                "750I",
                "M760I",
                "I7",
                "I7 SEDAN",
                "8 SERIES",
                "8 SERIES COUPE",
                "8 SERIES CONVERTIBLE",
                "8 SERIES GRAN COUPE",
                "M850I",
                "X3",
                "X4",
                "X5",
                "X5 HYBRID",
                "X6",
                "X7",
                "XM",
                "Z4",
                "Z4 M40I",
            }
        ),
        # No A/C bucket. NHTSA files evaporator complaints as UNKNOWN OR
        # OTHER / VISIBILITY (-> OTHER) and sometimes ELECTRICAL SYSTEM.
        allow_components=frozenset({"OTHER", "ELECTRICAL"}),
        # Both buckets are broad. Vehicle-only, so a Heikkila hit never
        # hides an unrelated BMW OTHER / ELECTRICAL cluster.
        same_defect=False,
        note=(
            "Heikkila v. BMW of North America, LLC (D.N.J. 2:26-cv-12932, "
            "filed 2026-10-02; CL docket 74910947). 2018-2025 G-chassis A/C "
            "evaporator corrosion (~1M vehicles). Attach only to BMW OTHER / "
            "ELECTRICAL (where A/C complaints land); vehicle-only because "
            "both buckets are broad. BMW is NOT in TRACKED_VEHICLES, and "
            "check_filings skips OTHER (no search terms), so this rule is "
            "inert until BMW is tracked."
        ),
    ),
)


def models_named_in_caption(caption: str) -> set[str]:
    """Uppercase model ids mentioned in a case caption.

    Longer tokens are listed first in `_MODEL_CAPTION_TOKENS`. Once a span
    is claimed (e.g. "ioniq 5"), a shorter overlapping token ("ioniq") is
    skipped so sibling checks are not poisoned by duplicate ids.
    """
    low = caption.lower()
    found: set[str] = set()
    consumed: list[tuple[int, int]] = []
    for token, model in _MODEL_CAPTION_TOKENS:
        for match in re.finditer(
            rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", low
        ):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in consumed):
                continue
            found.add(model)
            consumed.append(span)
    return found


def model_conflict(filing: Filing, make: str, model: str) -> bool:
    """True when the caption names a non-sibling model (wrong vehicle family).

    Example: Thieme caption naming Equinox/Terrain/Envision must not attach to
    CHEVROLET SUBURBAN BRAKES or GMC YUKON BRAKES.
    """
    named = models_named_in_caption(filing.case_name or "")
    if not named:
        return False
    siblings = MODEL_SIBLINGS.get(make.upper(), {}).get(model.upper())
    if siblings is None:
        return any(m != model.upper() for m in named)
    return any(m not in siblings for m in named)


def matching_rules(filing: Filing) -> list[CaptionRule]:
    cap = (filing.case_name or "").lower()
    return [r for r in CAPTION_RULES if any(s in cap for s in r.match_any)]


def allowed_by_corrections(
    filing: Filing, make: str, model: str, component: str
) -> bool:
    """Return False when a curated rule forbids this (make, model, component)."""
    rules = matching_rules(filing)
    if not rules:
        # No curated rule: sibling/caption model conflict is the only gate
        # (e.g. an Equinox-named suit must not land on Suburban).
        return not model_conflict(filing, make, model)
    # Curated allow-lists are authoritative. Skip model_conflict so a
    # multi-brand caption (Goldenkranz naming only Ioniq) can still attach
    # to EV6 / GV60 per allow_models across HYUNDAI/KIA/GENESIS.
    for rule in rules:
        if rule.deny_all:
            return False
        if make.upper() not in rule.allowed_makes():
            return False
        if rule.allow_models is not None and model.upper() not in rule.allow_models:
            return False
        if (
            rule.allow_components is not None
            and component.upper() not in rule.allow_components
        ):
            return False
    return True


def status_override(filing: Filing) -> str | None:
    for rule in matching_rules(filing):
        if rule.status_override:
            return rule.status_override
    return None


def same_defect_override(filing: Filing) -> bool | None:
    for rule in matching_rules(filing):
        if rule.same_defect is not None:
            return rule.same_defect
    return None


def correction_notes(filing: Filing) -> list[str]:
    return [r.note for r in matching_rules(filing) if r.note]
