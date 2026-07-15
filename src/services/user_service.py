"""Database operations for chat users."""

from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.chat_user import ChatUser


async def get_or_create_chat_user(
    session: AsyncSession,
    phone_number: str,
    display_name: Optional[str] = None,
) -> ChatUser:
    """Fetch existing user by channel key or create a new one."""
    stmt = select(ChatUser).where(ChatUser.phone_number == phone_number)
    existing = await session.scalar(stmt)
    if existing:
        return existing

    user = ChatUser(phone_number=phone_number, display_name=display_name)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing_after_race = await session.scalar(stmt)
        if existing_after_race:
            return existing_after_race
        raise

    await session.refresh(user)
    return user


async def list_chat_users(session: AsyncSession) -> List[ChatUser]:
    """Return known chat users (newest first)."""
    stmt = (
        select(ChatUser)
        .options(selectinload(ChatUser.skills))
        .order_by(desc(ChatUser.created_at))
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def get_chat_user_by_id(session: AsyncSession, user_id: int) -> Optional[ChatUser]:
    """Return chat user by primary key."""
    stmt = select(ChatUser).where(ChatUser.id == user_id)
    return await session.scalar(stmt)


async def save_user_resume_pdf(
    session: AsyncSession,
    user: ChatUser,
    pdf_bytes: bytes,
) -> ChatUser:
    """Store or replace the user's resume PDF."""
    user.resume_pdf = pdf_bytes
    await session.commit()
    await session.refresh(user)
    return user


async def update_user_job_search_preferences(
    session: AsyncSession,
    user: ChatUser,
    job_search_stage: Optional[str] = None,
    preferred_work_mode: Optional[str] = None,
    preferred_job_location: Optional[str] = None,
) -> ChatUser:
    """Update user job-search preference state used in messaging flow."""
    user.job_search_stage = job_search_stage
    user.preferred_work_mode = preferred_work_mode
    user.preferred_job_location = preferred_job_location
    await session.commit()
    await session.refresh(user)
    return user


async def update_user_display_name(
    session: AsyncSession,
    user: ChatUser,
    display_name: str,
) -> ChatUser:
    """Update user display name from CV extraction."""
    cleaned = display_name.strip()
    if not cleaned:
        return user
    user.display_name = cleaned
    await session.commit()
    await session.refresh(user)
    return user


async def delete_chat_user_by_id(session: AsyncSession, user_id: int) -> bool:
    """Delete a user by id. Returns True if deleted."""
    user = await get_chat_user_by_id(session, user_id)
    if not user:
        return False

    await session.delete(user)
    await session.commit()
    return True
