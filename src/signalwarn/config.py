"""Environment-driven configuration.

Loaded once at import time. All other modules read from `settings`.
"""
from __future__ import annotations

import json

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(..., description="Postgres connection string")

    anthropic_api_key: str = Field("", description="Claude API key for viability memos")
    anthropic_model: str = Field("claude-sonnet-4-6")

    resend_api_key: str = Field("", description="Resend API key for email alerts")
    alert_from_email: str = Field("signal@gofflawdfw.com")
    alert_to_email: str = Field("jim@gofflawdfw.com")

    # NHTSA publishes complaints weeks after they are filed, and the API has no
    # "published since" filter — the refresh job pulls each vehicle's full list
    # and keeps rows whose *filing* date is inside this window. A short window
    # silently drops every late-published complaint (that is what happened
    # between May and September 2026 with the old 7-day default). Duplicates
    # are impossible (ON CONFLICT on odi_number), so wide is safe.
    nhtsa_lookback_days: int = Field(180, ge=1, le=365)

    # Statute of limitations window, in years. A complaint whose incident date
    # (falling back to the NHTSA filing date) is older than this no longer
    # counts toward any cluster aggregate. Default 4 = UCC 2-725 warranty
    # limitations (borrowed by Magnuson-Moss) and Texas contract claims.
    # See docs/plans/2026-09-18-sol-and-filed-exclusion-design.md.
    sol_years: int = Field(4, ge=1, le=15)

    # CourtListener / Free Law Project — Phase 3a class action filing detection.
    # Token is optional; the public API works unauthenticated but is rate-limited
    # (~5K req/day). Authenticated users get a much higher ceiling.
    # Get one free at https://www.courtlistener.com/help/api/rest/#authentication
    courtlistener_api_token: str = Field("", description="CourtListener API token (optional)")

    # TypeSafe Jev — shadow judgments on each new viability memo, logged only
    # (no DB writes yet). Off by default; see signalwarn/jev_shadow.py.
    typesafe_api_key: str = Field("", description="TypeSafe API key for Jev shadow judgments")
    jev_model: str = Field("jev-1.13.0")
    jev_shadow_enabled: bool = Field(False, description="Send new memos to Jev and log answers")

    # Pinecone — Phase 2: semantic similarity across complaint narratives.
    # Phase 1 doesn't read these but they're recognized so .env loads cleanly.
    pinecone_api_key: str = Field("", description="Pinecone API key")
    pinecone_host: str = Field("", description="Pinecone index host URL")
    pinecone_index_name: str = Field("signal", description="Pinecone index name")

    # LangSmith — observability for Claude calls. Read directly by the SDK
    # via env vars; we declare them so pydantic doesn't warn.
    langsmith_api_key: str = Field("", description="LangSmith API key")
    langsmith_project: str = Field("signal", description="LangSmith project name")
    langsmith_tracing: bool = Field(False, description="Enable LangSmith tracing")
    langsmith_endpoint: str = Field("https://api.smith.langchain.com")

    signal_username: str = Field("jim")
    signal_password: str = Field("change-me")
    signal_users: str = Field(
        "",
        description='JSON dict of {"username": "password"} pairs. Takes precedence over '
                    'SIGNAL_USERNAME/SIGNAL_PASSWORD when set.',
    )

    def users(self) -> dict[str, str]:
        """Return the username→password map, supporting both single- and multi-user env."""
        if self.signal_users.strip():
            try:
                parsed = json.loads(self.signal_users)
                if isinstance(parsed, dict):
                    return {str(k): str(v) for k, v in parsed.items() if k and v}
            except json.JSONDecodeError:
                pass
        if self.signal_username and self.signal_password:
            return {self.signal_username: self.signal_password}
        return {}

    log_level: str = Field("INFO")
    environment: str = Field("development")


settings = Settings()  # type: ignore[call-arg]
