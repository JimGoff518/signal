"""Unit tests for the CourtListener client. No network calls."""
from __future__ import annotations

from datetime import date

from signalwarn.courtlistener import (
    COMPONENT_KEYWORDS,
    Filing,
    _parse_result,
    build_query,
)


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
