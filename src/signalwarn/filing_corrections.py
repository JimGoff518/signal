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
        "EQUINOX": frozenset({"EQUINOX", "TERRAIN", "ENVISION"}),
        "SUBURBAN": frozenset({"SUBURBAN", "TAHOE", "YUKON"}),
        "TAHOE": frozenset({"SUBURBAN", "TAHOE", "YUKON"}),
        "SILVERADO": frozenset({"SILVERADO", "SIERRA"}),
        "COLORADO": frozenset({"COLORADO", "CANYON"}),
    },
    "GMC": {
        "YUKON": frozenset({"YUKON", "SUBURBAN", "TAHOE"}),
        "SIERRA": frozenset({"SIERRA", "SILVERADO"}),
        "CANYON": frozenset({"CANYON", "COLORADO"}),
        "TERRAIN": frozenset({"TERRAIN", "EQUINOX", "ENVISION"}),
    },
    "BUICK": {
        "ENVISION": frozenset({"ENVISION", "EQUINOX", "TERRAIN"}),
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
    ("silverado", "SILVERADO"),
    ("suburban", "SUBURBAN"),
    ("colorado", "COLORADO"),
    ("equinox", "EQUINOX"),
    ("envision", "ENVISION"),
    ("terrain", "TERRAIN"),
    ("yukon", "YUKON"),
    ("tahoe", "TAHOE"),
    ("sierra", "SIERRA"),
    ("canyon", "CANYON"),
)


@dataclass(frozen=True)
class CaptionRule:
    """If the caption matches, constrain which clusters may accept the hit."""

    id: str
    match_any: tuple[str, ...]  # lowercase substrings
    allow_make: str
    allow_models: frozenset[str] | None  # None = any model of make
    allow_components: frozenset[str] | None  # None = any component
    status_override: str | None = None
    # When set, force class_action_same_defect rather than names_defect().
    same_defect: bool | None = None
    deny_all: bool = False
    note: str = ""


# P0 Scout watches: Norberg, Thieme, O'Connor (plus Petro so the two Ram
# engine tracks stay distinguishable when both captions appear).
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
)


def models_named_in_caption(caption: str) -> set[str]:
    """Uppercase model ids mentioned in a case caption."""
    low = caption.lower()
    found: set[str] = set()
    for token, model in _MODEL_CAPTION_TOKENS:
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", low):
            found.add(model)
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
    if model_conflict(filing, make, model):
        return False
    rules = matching_rules(filing)
    if not rules:
        return True
    for rule in rules:
        if rule.deny_all:
            return False
        if make.upper() != rule.allow_make.upper():
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
