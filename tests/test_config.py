"""Tests for the auth users resolver in Settings.users()."""
from __future__ import annotations

from signalwarn.config import Settings


def _make_settings(**overrides) -> Settings:
    base = {"database_url": "postgresql://x:x@localhost:5432/x"}
    base.update(overrides)
    return Settings(**base)


def test_single_user_fallback_to_username_password():
    s = _make_settings(signal_username="jim", signal_password="signal-prod")
    assert s.users() == {"jim": "signal-prod"}


def test_multi_user_via_signal_users_json():
    s = _make_settings(signal_users='{"jim":"abc","jack":"xyz"}')
    assert s.users() == {"jim": "abc", "jack": "xyz"}


def test_signal_users_takes_precedence_over_single_fallback():
    s = _make_settings(
        signal_username="jim",
        signal_password="ignored",
        signal_users='{"jack":"xyz"}',
    )
    assert s.users() == {"jack": "xyz"}


def test_malformed_json_falls_back_to_single_user():
    s = _make_settings(
        signal_username="jim",
        signal_password="signal-prod",
        signal_users="not-json",
    )
    assert s.users() == {"jim": "signal-prod"}


def test_empty_signal_users_falls_back():
    s = _make_settings(
        signal_username="jim",
        signal_password="signal-prod",
        signal_users="",
    )
    assert s.users() == {"jim": "signal-prod"}


def test_no_credentials_returns_empty():
    s = _make_settings(signal_username="", signal_password="", signal_users="")
    assert s.users() == {}
