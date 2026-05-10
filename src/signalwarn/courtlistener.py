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
import time
from dataclasses import dataclass
from datetime import date, timedelta

import requests

from signalwarn.config import settings

log = logging.getLogger(__name__)

API_BASE = "https://www.courtlistener.com/api/rest/v4"
DEFAULT_LOOKBACK_YEARS = 10


# Map NHTSA's normalized component buckets to richer keyword sets that show up
# in actual class-action filings. "ENGINE" alone is too generic; pairing it
# with "engine defect", "oil consumption", etc. matches more real filings.
COMPONENT_KEYWORDS: dict[str, str] = {
    "ENGINE": "engine OR oil consumption OR rod bearing",
    "TRANSMISSION": "transmission OR shudder OR shift",
    "BRAKES": "brake OR master cylinder OR vacuum pump",
    "FUEL SYSTEM": "fuel pump OR fuel injector OR fuel tank",
    "ELECTRICAL": "electrical OR fuel pump OR wiring",
    "STEERING": "steering OR power steering",
    "SUSPENSION": "suspension OR strut OR shock",
    "AIRBAG": "airbag OR Takata",
    "TIRES": "tire OR tread separation",
    "EXTERIOR": "paint OR rust OR corrosion",
    "SEATS": "seatbelt OR seat",
    "VEHICLE SPEED CONTROL": "unintended acceleration OR cruise control",
    "STRUCTURE": "frame OR roof OR structural",
    "OTHER": "",  # too generic to be useful — caller should skip
}


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
        min_interval_seconds: float = 0.6,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_token = api_token or settings.courtlistener_api_token or None
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

    def __enter__(self) -> "CourtListenerClient":
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
        """Search RECAP for dockets matching `q`. Returns up to `limit` filings."""
        self._throttle()
        floor = (date.today() - timedelta(days=365 * lookback_years)).isoformat()
        params = {
            "q": q,
            "type": "r",  # RECAP — federal docket entries
            "filed_after": floor,
            "order_by": "score desc",
        }
        try:
            resp = self._session.get(f"{API_BASE}/search/", params=params, timeout=self.timeout)
        except requests.RequestException as e:
            log.warning("CourtListener request failed for q=%r: %s", q, e)
            return []
        if resp.status_code == 429:
            log.warning("CourtListener rate-limited; sleeping 60s")
            time.sleep(60)
            return []
        if not resp.ok:
            log.warning("CourtListener %s for q=%r: %s", resp.status_code, q, resp.text[:200])
            return []
        results = (resp.json() or {}).get("results", [])
        return [_parse_result(r) for r in results[:limit]]


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
        case_name=str(r.get("caseName") or r.get("caseNameShort") or "(unknown)").strip(),
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


def find_class_action(client: CourtListenerClient, make: str, model: str,
                      component: str) -> Filing | None:
    """Convenience: return the top filing for (make, model, component) or None."""
    q = build_query(make, model, component)
    if q is None:
        return None
    results = client.search(q, limit=1)
    return results[0] if results else None
