"""CourtListener / Free Law Project API client.

Phase 3a — detect whether a class action has already been filed against a
manufacturer for a given product/component. If so, populate `class_action_filed`
on the cluster row, which triggers the -30 penalty in `signalwarn.scoring`.

The CourtListener search API is free and unauthenticated up to ~5K requests/day.
With an API token (https://www.courtlistener.com/help/api/rest/#authentication),
the rate ceiling is much higher. Token is optional; if unset the module works
fine for one-shot dashboards but should be set for routine daily polling.

Doc: https://www.courtlistener.com/help/api/rest/v4/

Design choices:
- We query the RECAP search (`type=r`) — this surfaces docket entries and
  matching dockets across federal courts, including the cases most relevant
  to product-liability class actions. RECAP is the open mirror of PACER.
- Query string is built per-cluster: `<manufacturer> <component> class action`
  with date filtering to the last 10 years.
- Polite throttling: 0.6s sleep between requests by default. Override via
  `min_interval_seconds` if you have a token and want to go faster.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import requests

from signalwarn.config import settings

log = logging.getLogger(__name__)

API_BASE = "https://www.courtlistener.com/api/rest/v4"
DEFAULT_LOOKBACK_YEARS = 10


class CourtListenerError(RuntimeError):
    """A lookup did not complete: throttled, transport failure, or 5xx.

    Distinct from an empty result on purpose. The filings check treats an
    empty list as "no class action on file" and marks the cluster checked;
    a failed lookup must not be recorded that way, or the cluster is never
    looked at again.
    """


# Map NHTSA's normalized component buckets to richer keyword sets that show up
# in actual class-action filings. "ENGINE" alone is too generic; pairing it
# with "engine defect", "oil consumption", etc. matches more real filings.
COMPONENT_KEYWORDS: dict[str, str] = {
    # Keys are the bucket names as they appear on the clusters table.
    "ENGINE": "engine OR oil consumption OR rod bearing",
    "POWER TRAIN": "transmission OR powertrain OR drivetrain OR shudder OR shift",
    "BRAKES": "brake OR master cylinder OR vacuum pump",
    "FUEL SYSTEM": "fuel pump OR fuel injector OR fuel tank",
    "ELECTRICAL": "electrical OR wiring OR battery OR infotainment",
    "STEERING": "steering OR power steering",
    "SUSPENSION": "suspension OR strut OR shock",
    "AIR BAGS": "airbag OR air bag OR Takata OR inflator",
    "SEAT BELTS": "seatbelt OR seat belt OR seat",
    "SPEED CONTROL": "unintended acceleration OR cruise control OR throttle",
    "LIGHTING": "headlight OR headlamp OR tail light OR lighting",
    "TIRES": "tire OR tread separation",
    "STRUCTURE": "frame OR roof OR structural OR sunroof OR windshield",
    "EXTERIOR": "paint OR rust OR corrosion",
    # Older shorthand kept so nothing that passes these breaks.
    "TRANSMISSION": "transmission OR shudder OR shift",
    "AIRBAG": "airbag OR Takata",
    "SEATS": "seatbelt OR seat",
    "VEHICLE SPEED CONTROL": "unintended acceleration OR cruise control",
    "OTHER": "",  # too generic to be useful — caller should skip
}

# Words that must appear in a case caption for a search hit to count as a
# class action against this manufacturer. RECAP search is full-text over
# docket entries, so without this check the top hit for "Ram" "1500" was a
# pension fund called Local 1500 suing a drug company (2026-09-19 run).
# Parent and holding companies are listed because the defendant is usually
# the corporate entity, not the brand. Corporate cousins that are separate
# legal entities (Hyundai / Kia) are deliberately NOT cross-listed.
MANUFACTURER_ALIASES: dict[str, tuple[str, ...]] = {
    "FORD": ("ford",),
    "CHEVROLET": ("general motors", "chevrolet"),
    "GMC": ("general motors", "gmc"),
    "JEEP": ("fca", "chrysler", "stellantis", "jeep"),
    "RAM": ("fca", "chrysler", "stellantis", "ram truck"),
    "HONDA": ("honda", "acura"),
    "TOYOTA": ("toyota", "lexus"),
    "HYUNDAI": ("hyundai",),
    "KIA": ("kia",),
    "NISSAN": ("nissan", "infiniti"),
    "TESLA": ("tesla",),
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_caption(raw: str) -> str:
    """Strip the HTML and clerk formatting CourtListener leaves in caseName."""
    return _WS_RE.sub(" ", _HTML_TAG_RE.sub(" ", raw)).strip()


@dataclass
class Filing:
    """A single matching docket from CourtListener search results."""
    case_name: str
    court: str
    date_filed: date | None
    docket_number: str
    absolute_url: str  # path on courtlistener.com — prepend the host
    suit_nature: str = ""  # e.g. "Personal Injury - Product Liability"
    date_terminated: date | None = None  # NULL if still pending

    @property
    def url(self) -> str:
        if not self.absolute_url:
            return ""
        if self.absolute_url.startswith("http"):
            return self.absolute_url
        return f"https://www.courtlistener.com{self.absolute_url}"

    @property
    def status(self) -> str:
        """'terminated' if dateTerminated is set, else 'pending'.

        Per Jim's call (2026-05-09): once a case is terminated — whether by
        settlement, dismissal, summary judgment for defendant, certification
        of a different class counsel, or any other resolution — the cluster
        should be hidden from the dashboard rather than shown with a -30
        penalty. Class counsel has been chosen / case is closed = no money
        for a new firm.
        """
        return "terminated" if self.date_terminated is not None else "pending"


class CourtListenerClient:
    """Thin requests wrapper with token auth and polite throttling."""

    def __init__(
        self,
        api_token: str | None = None,
        min_interval_seconds: float | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_token = api_token or settings.courtlistener_api_token or None
        # Anonymous callers get throttled around 0.6s; the first live run
        # took 25 one-minute penalties at that pace. Back off unless a
        # token is present or the caller says otherwise.
        if min_interval_seconds is None:
            min_interval_seconds = 0.6 if self.api_token else 1.5
        self.min_interval = min_interval_seconds
        self.timeout = timeout_seconds
        self._last_request_at = 0.0
        self._session = requests.Session()
        if self.api_token:
            self._session.headers["Authorization"] = f"Token {self.api_token}"
        # HTTP headers must be ASCII — no em-dashes, smart quotes, etc.
        self._session.headers["User-Agent"] = (
            "SIGNAL/0.1 (+https://github.com/JimGoff518/signal) - class-action "
            "detection for Goff Law PLLC"
        )

    def __enter__(self) -> CourtListenerClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._session.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def search(self, q: str, *, lookback_years: int = DEFAULT_LOOKBACK_YEARS,
               limit: int = 5) -> list[Filing]:
        """Search RECAP for dockets matching `q`. Returns up to `limit` filings.

        An empty list means the index has nothing for this query. Anything
        that stops the lookup from completing raises CourtListenerError so
        the caller can leave the cluster unchecked and try again later.
        A 429 is retried once after a 60s pause.
        """
        floor = (date.today() - timedelta(days=365 * lookback_years)).isoformat()
        params = {
            "q": q,
            "type": "r",  # RECAP — federal docket entries
            "filed_after": floor,
            "order_by": "score desc",
        }
        for attempt in (1, 2):
            self._throttle()
            try:
                resp = self._session.get(
                    f"{API_BASE}/search/", params=params, timeout=self.timeout
                )
            except requests.RequestException as e:
                raise CourtListenerError(f"request failed for q={q!r}: {e}") from e
            if resp.status_code == 429:
                if attempt == 1:
                    log.warning("CourtListener rate-limited; sleeping 60s then retrying")
                    time.sleep(60)
                    continue
                raise CourtListenerError(f"rate-limited twice for q={q!r}")
            if not resp.ok:
                raise CourtListenerError(
                    f"HTTP {resp.status_code} for q={q!r}: {resp.text[:200]}"
                )
            results = (resp.json() or {}).get("results", [])
            return [_parse_result(r) for r in results[:limit]]
        raise CourtListenerError(f"unreachable for q={q!r}")  # pragma: no cover


def _parse_iso_date(raw: object) -> date | None:
    """Best-effort ISO-date parse; returns None on bad input."""
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def _parse_result(r: dict) -> Filing:
    """Pull the fields we care about out of a search result.

    The v4 API returns `docket_absolute_url` for RECAP search hits; older
    endpoints used `absolute_url`. Try both so the parser keeps working if
    the field name shifts again.
    """
    return Filing(
        case_name=_clean_caption(str(r.get("caseName") or r.get("caseNameShort") or "(unknown)")),
        court=str(r.get("court") or r.get("court_id") or "").strip(),
        date_filed=_parse_iso_date(r.get("dateFiled")),
        docket_number=str(r.get("docketNumber") or "").strip(),
        absolute_url=str(
            r.get("docket_absolute_url") or r.get("absolute_url") or ""
        ).strip(),
        suit_nature=str(r.get("suitNature") or "").strip(),
        date_terminated=_parse_iso_date(r.get("dateTerminated")),
    )


def build_query(make: str, model: str, component: str) -> str | None:
    """Construct a CourtListener query for a (make, model, component) cluster.

    Returns None if the component is too generic (e.g. "OTHER") to produce
    useful matches — callers should skip those clusters rather than burn API
    quota on noise.
    """
    component_terms = COMPONENT_KEYWORDS.get(component.upper(), component.lower())
    if not component_terms:
        return None
    return f'"{make.title()}" "{model.title()}" ({component_terms}) "class action"'


def is_plausible_filing(filing: Filing, make: str) -> bool:
    """Is this search hit actually a case against `make`'s manufacturer?

    Two checks. The caption must name the manufacturer or its parent
    (see MANUFACTURER_ALIASES), and the court must not be a bankruptcy
    court. Both are cheap and both rule out the false positives the first
    live run produced.
    """
    if "bankruptcy" in filing.court.lower():
        return False
    caption = filing.case_name.lower()
    aliases = MANUFACTURER_ALIASES.get(make.upper(), (make.lower(),))
    return any(alias in caption for alias in aliases)


def names_defect(filing: Filing, component: str) -> bool:
    """Does the case caption itself name this cluster's component?

    Captions rarely do, so this is deliberately narrow: it is TRUE for
    consolidated matters like "In re: Kia Engine Litigation" or "CP4 Fuel
    Pump Litigation" and FALSE for "Smith v. Ford". Only a TRUE here hides
    the cluster from the dashboard; see EXCLUDE_FILED_SQL in clustering.
    """
    terms = COMPONENT_KEYWORDS.get(component.upper(), "")
    if not terms:
        return False
    caption = filing.case_name.lower()
    # Whole words only: "shock" must not match a plaintiff named Shockley,
    # and "seat" must not match Seattle.
    return any(
        re.search(rf"\b{re.escape(t.strip().lower())}\b", caption)
        for t in terms.split(" OR ")
        if t.strip()
    )


def find_class_action(client: CourtListenerClient, make: str, model: str,
                      component: str) -> Filing | None:
    """Return the best plausible filing for (make, model, component), or None.

    Asks for several hits and returns the first that passes
    `is_plausible_filing`, so a noisy top result does not poison the cluster.
    """
    q = build_query(make, model, component)
    if q is None:
        return None
    for filing in client.search(q, limit=5):
        if is_plausible_filing(filing, make):
            return filing
    return None
