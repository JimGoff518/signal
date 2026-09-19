"""Unit tests for the CourtListener client. No network calls."""
from __future__ import annotations

from datetime import date

import pytest
import requests

from signalwarn.courtlistener import (
    COMPONENT_KEYWORDS,
    MANUFACTURER_ALIASES,
    CourtListenerClient,
    CourtListenerError,
    Filing,
    _parse_result,
    build_query,
    find_class_action,
    is_plausible_filing,
)

# ─── Failed lookups must not look like "no case found" ──────────────────
# The first live run hit 25 rate-limit pauses and 7 request failures; each
# one returned [] and the caller marked the cluster checked-and-clean.


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = ""
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)
        self.headers = {}
        self.calls = 0

    def get(self, *_, **__):
        self.calls += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def close(self):
        pass


def _client(responses, monkeypatch) -> CourtListenerClient:
    c = CourtListenerClient(api_token="", min_interval_seconds=0)
    c._session = _Session(responses)
    monkeypatch.setattr("signalwarn.courtlistener.time.sleep", lambda _s: None)
    return c


def test_search_raises_when_rate_limited_twice(monkeypatch):
    c = _client([_Resp(429), _Resp(429)], monkeypatch)
    with pytest.raises(CourtListenerError):
        c.search("q")
    assert c._session.calls == 2  # one retry, then give up


def test_search_retries_once_after_rate_limit(monkeypatch):
    hit = {"caseName": "Doe v. Ford Motor Company", "court": "E.D. Mich."}
    c = _client([_Resp(429), _Resp(200, {"results": [hit]})], monkeypatch)
    assert [f.case_name for f in c.search("q")] == ["Doe v. Ford Motor Company"]


def test_search_raises_on_transport_error(monkeypatch):
    c = _client([requests.ConnectionError("boom")], monkeypatch)
    with pytest.raises(CourtListenerError):
        c.search("q")


def test_search_raises_on_server_error(monkeypatch):
    c = _client([_Resp(503)], monkeypatch)
    with pytest.raises(CourtListenerError):
        c.search("q")


def test_anonymous_client_throttles_harder_than_authenticated():
    assert CourtListenerClient(api_token="").min_interval > CourtListenerClient(
        api_token="tok"
    ).min_interval


def test_search_empty_results_is_a_real_empty_list(monkeypatch):
    c = _client([_Resp(200, {"results": []})], monkeypatch)
    assert c.search("q") == []


def _filing(name: str, court: str = "District Court, E.D. Michigan") -> Filing:
    return Filing(
        case_name=name,
        court=court,
        date_filed=date(2024, 1, 1),
        docket_number="1:24-cv-00001",
        absolute_url="/docket/1/",
    )


# ─── Match validation (added after the first live run matched pension
# funds and drug companies to pickup trucks) ────────────────────────────


def test_plausible_filing_requires_manufacturer_in_caption():
    assert is_plausible_filing(_filing("Norman v. FCA US, LLC"), "RAM")
    assert is_plausible_filing(_filing("Hermanowicz v. General Motors, LLC"), "CHEVROLET")
    assert is_plausible_filing(
        _filing("In re: General Motors LLC CP4 Fuel Pump Litigation"), "GMC"
    )
    # Real false positives from the 2026-09-19 run.
    assert not is_plausible_filing(
        _filing("UFCW Local 1500 Welfare Fund v. Takeda Pharmaceuticals USA, Inc."), "RAM"
    )
    assert not is_plausible_filing(
        _filing("Michiana Area Electrical Workers' Pension Fund v. Inari Medical, Inc."),
        "RAM",
    )
    assert not is_plausible_filing(_filing("DINITZ v. VERISK ANALYTICS, INC."), "CHEVROLET")


def test_plausible_filing_rejects_bankruptcy_court():
    f = _filing(
        "Tyler Jacob Pressdee and Alexis Marie Pressdee",
        court="United States Bankruptcy Court, W.D. North Carolina",
    )
    assert not is_plausible_filing(f, "CHEVROLET")


def test_plausible_filing_does_not_cross_manufacturers():
    # Same corporate group, different legal entity: not the same defendant.
    assert not is_plausible_filing(_filing("Musgrave v. Hyundai Motor America, Inc."), "KIA")


def test_plausible_filing_accepts_parent_company_names():
    assert is_plausible_filing(_filing("Frisch v. FCA US, LLC"), "JEEP")
    assert is_plausible_filing(_filing("Doe v. Stellantis N.V."), "RAM")
    assert is_plausible_filing(_filing("Doe v. American Honda Motor Co., Inc."), "HONDA")


def test_manufacturer_aliases_cover_every_tracked_make():
    from signalwarn.ingestion import TRACKED_VEHICLES

    for make in {v[0] for v in TRACKED_VEHICLES}:
        assert make in MANUFACTURER_ALIASES, make


def test_parse_result_strips_html_from_case_name():
    raw = 'Flick v. Toyota Motor Corporation<b><font color="red">PURSUANT TO ORDER</font></b>'
    assert _parse_result({"caseName": raw, "court": "x"}).case_name == (
        "Flick v. Toyota Motor Corporation PURSUANT TO ORDER"
    )


class _FakeClient:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def search(self, q, *, limit=5, **_):
        self.calls.append((q, limit))
        return self._results[:limit]


def test_find_class_action_skips_implausible_top_hit():
    client = _FakeClient(
        [
            _filing("UFCW Local 1500 Welfare Fund v. Takeda Pharmaceuticals USA, Inc."),
            _filing("Norman v. FCA US, LLC"),
        ]
    )
    f = find_class_action(client, "RAM", "1500", "POWER TRAIN")
    assert f is not None and f.case_name.startswith("Norman")
    assert client.calls[0][1] >= 5  # asks for more than one so it has fallbacks


def test_find_class_action_returns_none_when_nothing_plausible():
    client = _FakeClient(
        [_filing("UFCW Local 1500 Welfare Fund v. Takeda Pharmaceuticals USA, Inc.")]
    )
    assert find_class_action(client, "RAM", "1500", "POWER TRAIN") is None


# ─── Query construction ─────────────────────────────────────────────────

def test_build_query_includes_make_model_component_and_class_action_phrase():
    q = build_query("FORD", "EXPLORER", "STEERING")
    assert q is not None
    assert "Ford" in q
    assert "Explorer" in q
    assert "class action" in q
    # Component keyword expansion should kick in:
    assert "steering" in q or "power steering" in q


def test_build_query_returns_none_for_other_component():
    """The 'OTHER' component bucket is too generic — wasted API call."""
    assert build_query("KIA", "SORENTO", "OTHER") is None


def test_build_query_handles_unknown_component_gracefully():
    """Components we haven't pre-mapped should still produce a usable query
    (using the component name itself as the keyword)."""
    q = build_query("ACME", "WIDGET", "FLUX_CAPACITOR")
    assert q is not None
    assert "flux_capacitor" in q.lower()


def test_component_keyword_map_covers_canonical_buckets():
    """Catches future canonical components missing from the keyword map."""
    expected = {
        "ENGINE", "TRANSMISSION", "BRAKES", "FUEL SYSTEM", "ELECTRICAL",
        "STEERING", "AIRBAG",
    }
    assert expected.issubset(set(COMPONENT_KEYWORDS.keys()))


# ─── Response parsing ───────────────────────────────────────────────────

def test_parse_result_extracts_full_record():
    raw = {
        "caseName": "Smith v. Ford Motor Company",
        "court": "Northern District of California",
        "dateFiled": "2024-05-15",
        "docketNumber": "3:24-cv-01234",
        "absolute_url": "/docket/12345/smith-v-ford-motor-company/",
    }
    f = _parse_result(raw)
    assert f.case_name == "Smith v. Ford Motor Company"
    assert f.court == "Northern District of California"
    assert f.date_filed == date(2024, 5, 15)
    assert f.docket_number == "3:24-cv-01234"
    assert f.url == "https://www.courtlistener.com/docket/12345/smith-v-ford-motor-company/"


def test_parse_result_handles_missing_date():
    f = _parse_result({"caseName": "Foo v. Bar", "absolute_url": "/x"})
    assert f.date_filed is None
    assert f.case_name == "Foo v. Bar"


def test_parse_result_handles_missing_case_name():
    f = _parse_result({"absolute_url": "/x"})
    assert f.case_name == "(unknown)"


def test_parse_result_handles_already_qualified_url():
    """If absolute_url already starts with http, don't double-prefix the host."""
    f = _parse_result({
        "caseName": "X",
        "absolute_url": "https://example.com/docket/1/",
    })
    assert f.url == "https://example.com/docket/1/"


def test_parse_result_prefers_v4_docket_absolute_url():
    """v4 of the API uses `docket_absolute_url` for RECAP hits; older endpoints
    used `absolute_url`. Make sure the v4 field is recognized."""
    f = _parse_result({
        "caseName": "Coolidge v. Ford Motor Company",
        "docket_absolute_url": "/docket/67511005/coolidge-v-ford-motor-company/",
        "suitNature": "Personal Injury - Product Liability",
    })
    assert f.url == (
        "https://www.courtlistener.com/docket/67511005/coolidge-v-ford-motor-company/"
    )
    assert f.suit_nature == "Personal Injury - Product Liability"


def test_parse_result_empty_url_returns_empty_string():
    """A result with no URL shouldn't return the bare host."""
    f = _parse_result({"caseName": "X"})
    assert f.url == ""


def test_parse_result_handles_malformed_date_gracefully():
    """A garbage date string shouldn't blow up parsing."""
    f = _parse_result({"caseName": "X", "dateFiled": "not-a-date", "absolute_url": "/x"})
    assert f.date_filed is None


# ─── Filing dataclass ───────────────────────────────────────────────────

def test_filing_url_property():
    f = Filing(case_name="X", court="Y", date_filed=None, docket_number="Z",
               absolute_url="/foo")
    assert f.url == "https://www.courtlistener.com/foo"


# ─── Case status (pending vs terminated) ────────────────────────────────

def test_filing_status_pending_when_not_terminated():
    f = Filing(case_name="X", court="Y", date_filed=date(2024, 1, 1),
               docket_number="Z", absolute_url="/foo", date_terminated=None)
    assert f.status == "pending"


def test_filing_status_terminated_when_termination_date_set():
    f = Filing(case_name="X", court="Y", date_filed=date(2020, 1, 1),
               docket_number="Z", absolute_url="/foo",
               date_terminated=date(2024, 6, 1))
    assert f.status == "terminated"


def test_parse_result_captures_termination_date():
    f = _parse_result({
        "caseName": "Old v. Acme",
        "dateFiled": "2018-01-01",
        "dateTerminated": "2022-06-15",
        "docket_absolute_url": "/x",
    })
    assert f.date_terminated == date(2022, 6, 15)
    assert f.status == "terminated"


def test_parse_result_pending_when_no_termination_date():
    f = _parse_result({
        "caseName": "New v. Acme",
        "dateFiled": "2025-01-01",
        "docket_absolute_url": "/x",
        # no dateTerminated key
    })
    assert f.date_terminated is None
    assert f.status == "pending"


def test_parse_result_handles_malformed_termination_date():
    f = _parse_result({
        "caseName": "X",
        "dateTerminated": "garbage",
        "docket_absolute_url": "/x",
    })
    assert f.date_terminated is None
    assert f.status == "pending"
