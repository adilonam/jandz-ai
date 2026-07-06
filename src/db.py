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
    connect_args=settings.DB_CONNECT_ARGS,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

DEFAULT_SKILLS = [
    ("Healthcare", "Registered nurses"),
    ("Healthcare", "Nurse practitioners"),
    ("Healthcare", "Psychiatrists"),
    ("Healthcare", "Medical laboratory scientists"),
    ("Healthcare", "Radiographers"),
    ("Healthcare", "Pharmacists"),
    ("Healthcare", "Caregivers"),
    ("Healthcare", "Physiotherapists"),
    ("Healthcare", "Public health specialists"),
    ("Healthcare", "Clinical researchers"),
    ("Technology", "Software engineer"),
    ("Technology", "Graphics Designer"),
    ("Technology", "Data scientist"),
    ("Technology", "Data analyst"),
    ("Technology", "AI/ML engineer"),
    ("Technology", "Cybersecurity analyst"),
    ("Technology", "Cloud engineer"),
    ("Technology", "DevOps engineer"),
    ("Technology", "Product manager"),
    ("Technology", "UI/UX designer"),
    ("Technology", "QA engineer"),
    ("Technology", "Digital marketing"),
    ("Technology", "E-commerce service"),
    ("Technology", "Graphics Design"),
    ("Technology", "NFTs & Web3.0"),
    ("Skilled Trades", "Welder"),
    ("Skilled Trades", "Electrician"),
    ("Skilled Trades", "Plumber"),
    ("Skilled Trades", "HVAC technician"),
    ("Skilled Trades", "Automotive technician"),
    ("Skilled Trades", "Heavy equipment operator"),
    ("Skilled Trades", "Truck driver"),
    ("Education", "STEM teacher"),
    ("Education", "Special education teacher"),
    ("Education", "ESL teacher"),
    ("Education", "University lecturer"),
    ("Education", "Researchers"),
    ("Creative and Digital Economy", "Content creators"),
    ("Creative and Digital Economy", "Animators"),
    ("Creative and Digital Economy", "Digital marketers"),
    ("Creative and Digital Economy", "Video editors"),
    ("Creative and Digital Economy", "Social media managers"),
]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create DB tables for first-run/dev environments."""
    from src.models.conversation_message import ConversationMessage  # noqa: F401
    from src.models.job_search_history import JobSearchHistory  # noqa: F401
    from src.models.whatsapp_user import WhatsAppUser  # noqa: F401
    from src.models.skill import Skill  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Keep existing dev DBs compatible when new columns are added.
        await conn.execute(
            text("ALTER TABLE whatsapp_users ADD COLUMN IF NOT EXISTS resume_pdf BYTEA")
        )
        await conn.execute(
            text("ALTER TABLE whatsapp_users ADD COLUMN IF NOT EXISTS job_search_stage VARCHAR(32)")
        )
        await conn.execute(
            text("ALTER TABLE whatsapp_users ADD COLUMN IF NOT EXISTS preferred_work_mode VARCHAR(16)")
        )
        await conn.execute(
            text(
                "ALTER TABLE whatsapp_users ADD COLUMN IF NOT EXISTS preferred_job_location VARCHAR(120)"
            )
        )
        await conn.execute(
            text("ALTER TABLE skills ADD COLUMN IF NOT EXISTS category VARCHAR(120)")
        )
        await conn.execute(
            text("UPDATE skills SET category = 'General' WHERE category IS NULL OR category = ''")
        )

        upsert_success_count = 0
        upsert_failure_count = 0
        for category, skill_name in DEFAULT_SKILLS:
            try:
                await conn.execute(
                    text(
                        "INSERT INTO skills (category, name) VALUES (:category, :name) "
                        "ON CONFLICT (name) DO UPDATE SET category = EXCLUDED.category"
                    ),
                    {"category": category, "name": skill_name},
                )
                upsert_success_count += 1
                print(f"[init_db] upserted skill: category='{category}' name='{skill_name}'")
            except Exception as exc:
                upsert_failure_count += 1
                print(
                    "[init_db] failed upsert for skill: "
                    f"category='{category}' name='{skill_name}' error='{exc}'"
                )
                raise

        print(
            "[init_db] skills seed completed: "
            f"success={upsert_success_count} failed={upsert_failure_count}"
        )
