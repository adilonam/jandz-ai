"""Database setup and session management."""

from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings


class Base(DeclarativeBase):
    """Base model for SQLAlchemy declarative mappings."""


if not settings.ASYNC_DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required to start the application.")

engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

DEFAULT_SKILLS = [
    "Programming & Tech",
    "Data",
    "AI Services",
    "Graphics & Design",
    "Video & Animation",
    "Music & Audio",
    "Digital Marketing",
    "Business",
    "Consulting",
    "Writing & Translation",
    "Lifestyle",
    "E-commerce Services",
    "NFTs & Web3",
]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create DB tables for first-run/dev environments."""
    from src.models.whatsapp_user import WhatsAppUser  # noqa: F401
    from src.models.skill import Skill  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Keep existing dev DBs compatible when new columns are added.
        await conn.execute(
            text("ALTER TABLE whatsapp_users ADD COLUMN IF NOT EXISTS resume_pdf BYTEA")
        )
        for skill_name in DEFAULT_SKILLS:
            await conn.execute(
                text(
                    "INSERT INTO skills (name) VALUES (:name) "
                    "ON CONFLICT (name) DO NOTHING"
                ),
                {"name": skill_name},
            )
