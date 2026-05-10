"""Database operations for WhatsApp users."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
