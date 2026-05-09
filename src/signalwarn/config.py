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

    nhtsa_lookback_days: int = Field(7, ge=1, le=365)

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
