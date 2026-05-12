"""Database operations for WhatsApp users."""

from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.whatsapp_user import WhatsAppUser


async def get_or_create_whatsapp_user(
    session: AsyncSession,
    phone_number: str,
    display_name: Optional[str] = None,
) -> WhatsAppUser:
    """Fetch existing user by phone or create a new one."""
    stmt = select(WhatsAppUser).where(WhatsAppUser.phone_number == phone_number)
    existing = await session.scalar(stmt)
    if existing:
        return existing

    user = WhatsAppUser(phone_number=phone_number, display_name=display_name)
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


async def list_whatsapp_users(session: AsyncSession) -> List[WhatsAppUser]:
    """Return known WhatsApp users (newest first)."""
    stmt = (
        select(WhatsAppUser)
        .options(selectinload(WhatsAppUser.skills))
        .order_by(desc(WhatsAppUser.created_at))
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def get_whatsapp_user_by_id(session: AsyncSession, user_id: int) -> Optional[WhatsAppUser]:
    """Return WhatsApp user by primary key."""
    stmt = select(WhatsAppUser).where(WhatsAppUser.id == user_id)
    return await session.scalar(stmt)


async def save_user_resume_pdf(
    session: AsyncSession,
    user: WhatsAppUser,
    pdf_bytes: bytes,
) -> WhatsAppUser:
    """Store or replace the user's resume PDF."""
    user.resume_pdf = pdf_bytes
    await session.commit()
    await session.refresh(user)
    return user


async def delete_whatsapp_user_by_id(session: AsyncSession, user_id: int) -> bool:
    """Delete a user by id. Returns True if deleted."""
    user = await get_whatsapp_user_by_id(session, user_id)
    if not user:
        return False

    await session.delete(user)
    await session.commit()
    return True
