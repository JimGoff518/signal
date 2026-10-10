"""Memo-per-run and digest-size caps."""
from __future__ import annotations

from signalwarn import alerts, viability
from signalwarn.config import Settings
from tests._fakes import FakeConn, fake_connection


def _settings(**kw):
    return Settings(database_url="postgresql://x/y", **kw)


def test_cap_defaults_and_empty_means_unlimited():
    s = _settings()
    assert s.memo_max_per_run == 25 and s.digest_max_items == 10
    s = _settings(memo_max_per_run="", digest_max_items="")
    assert s.memo_max_per_run is None and s.digest_max_items is None


def test_memo_pass_counts_only_written(monkeypatch):
    monkeypatch.setattr(viability, "memo_candidate_ids", lambda: list(range(10)))
    seen = []

    def fake_regen(cid):
        seen.append(cid)
        if cid == 2:
            raise RuntimeError("boom")
        return cid % 2 == 0  # odd ids skipped (no write)

    monkeypatch.setattr(viability, "regenerate_memo_if_needed", fake_regen)
    written, remaining = viability.run_memo_pass(2)
    # 0 written, 1 skip, 2 fails, 3 skip, 4 written -> cap hit
    assert written == 2 and seen == [0, 1, 2, 3, 4] and remaining == 5


def test_memo_pass_unlimited(monkeypatch):
    monkeypatch.setattr(viability, "memo_candidate_ids", lambda: [1, 2, 3])
    monkeypatch.setattr(viability, "regenerate_memo_if_needed", lambda cid: True)
    assert viability.run_memo_pass(None) == (3, 0)


def _row(i, score, cls="HOT"):
    return {"id": i, "score": score, "classification": cls, "model_year": 2024,
            "make": "FORD", "model": f"M{i}", "component": "BRAKES", "complaint_count": 5}


def _digest(monkeypatch, rows, cap):
    monkeypatch.setattr(alerts, "connection", fake_connection(FakeConn([rows])))
    monkeypatch.setattr(alerts.settings, "digest_max_items", cap)
    sent = []
    monkeypatch.setattr(alerts, "_send", lambda subj, html: sent.append(html))
    alerts.send_daily_digest()
    return sent[0]


def test_digest_caps_to_top_n_and_notes_omitted(monkeypatch):
    rows = [_row(i, 100 - i, "CRITICAL" if i < 3 else "HOT") for i in range(15)]
    html = _digest(monkeypatch, rows, 10)
    assert html.count("<li>") == 10
    assert "M9 " in html and "M10 " not in html
    assert "5 more" in html


def test_digest_under_cap_has_no_omitted_line(monkeypatch):
    html = _digest(monkeypatch, [_row(i, 90 - i) for i in range(4)], 10)
    assert html.count("<li>") == 4 and "omitted" not in html


def test_digest_unlimited(monkeypatch):
    html = _digest(monkeypatch, [_row(i, 90 - i) for i in range(30)], None)
    assert html.count("<li>") == 30
