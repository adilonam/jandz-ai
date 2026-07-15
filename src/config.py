"""Application configuration."""

import os
from typing import Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv()


def _normalize_env(value: Optional[str]) -> str:
    """Return ``dev`` or ``prod``; unknown/empty values default to ``dev``."""
    normalized = (value or "").strip().lower()
    if normalized in {"dev", "prod"}:
        return normalized
    return "dev"


class Settings:
    """Environment-driven settings for the API."""

    APP_NAME = os.getenv("APP_NAME", "jandz-ai").strip() or "jandz-ai"
    APP_VERSION = "0.1.0"
    APP_DESCRIPTION = "Telegram + OpenAI FastAPI service."

    ENV = _normalize_env(os.getenv("ENV", "dev"))

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    CORESIGNAL_API_KEY = os.getenv("CORESIGNAL_API_KEY", "").strip()
    OPENAI_AUDIO_MODEL = (
        os.getenv("OPENAI_AUDIO_MODEL", "gpt-4o-mini-transcribe").strip()
        or "gpt-4o-mini-transcribe"
    )
    JOBS_TO_SHOW = max(1, int((os.getenv("JOBS_TO_SHOW", "5") or "5").strip()))
    OPENAI_SYSTEM_PROMPT = (
        "You are a friendly guide on Telegram helping students and people find "
        "education or job opportunities. Keep answers concise and clear. "
        "When relevant, invite them to reply with education or jobs for tailored suggestions."
    )

    ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "").strip()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
    ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "").strip()

    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Return a SQLAlchemy asyncpg URL compatible with common hosted Postgres URLs."""
        if not self.DATABASE_URL:
            return self.DATABASE_URL

        parsed = urlsplit(self.DATABASE_URL)
        scheme = parsed.scheme
        if scheme == "postgresql":
            scheme = "postgresql+asyncpg"
        elif scheme == "postgres":
            scheme = "postgresql+asyncpg"
        else:
            return self.DATABASE_URL

        query_params = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key != "sslmode"
        ]
        return urlunsplit(
            (
                scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query_params),
                parsed.fragment,
            )
        )

    @property
    def DB_CONNECT_ARGS(self) -> Dict[str, bool]:
        """Map libpq-style sslmode to asyncpg's ssl argument."""
        parsed = urlsplit(self.DATABASE_URL)
        sslmode = dict(parse_qsl(parsed.query, keep_blank_values=True)).get("sslmode")
        if sslmode in {"require", "verify-ca", "verify-full"}:
            return {"ssl": True}
        return {}


settings = Settings()


def format_outbound_message(body: str) -> str:
    """Prefix outbound bot text with ``[dev]`` when ``ENV`` is ``dev``."""
    if settings.ENV != "dev":
        return body
    if body.startswith("[dev]"):
        return body
    return f"[dev] {body}"
