"""Application configuration."""

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Environment-driven settings for the API."""

    APP_NAME = "jandz-ai API"
    APP_VERSION = "0.1.0"
    APP_DESCRIPTION = "WhatsApp + OpenAI FastAPI service."

    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    WHATSAPP_GRAPH_API_VERSION = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v21.0").strip() or "v21.0"

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    OPENAI_SYSTEM_PROMPT = (
        "You are a helpful assistant chatting with users on WhatsApp. "
        "Keep answers concise and clear."
    )

    ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "").strip()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
    ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "").strip()

    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        if self.DATABASE_URL.startswith("postgres://"):
            return self.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
        return self.DATABASE_URL


settings = Settings()
