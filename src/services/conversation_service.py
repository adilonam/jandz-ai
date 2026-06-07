"""Conversation history service operations."""

from typing import List

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.conversation_message import ConversationMessage
from src.models.whatsapp_user import WhatsAppUser


async def create_conversation_message(
    session: AsyncSession,
    user_id: int,
    direction: str,
    text: str,
    channel: str = "whatsapp",
) -> ConversationMessage:
    """Persist one message row."""
    message = ConversationMessage(
        user_id=user_id,
        direction=direction,
        channel=channel,
        text=text,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def list_conversation_messages(
    session: AsyncSession,
    limit: int = 400,
) -> List[ConversationMessage]:
    """Return newest conversation messages with linked users."""
    stmt = (
        select(ConversationMessage)
        .options(selectinload(ConversationMessage.user))
        .order_by(desc(ConversationMessage.created_at))
        .limit(limit)
    )
    rows = await session.scalars(stmt)
    return list(rows.all())


async def list_conversation_user_summaries(session: AsyncSession) -> List[dict]:
    """Return one row per user with message count and last message time."""
    stmt = (
        select(
            WhatsAppUser.id,
            WhatsAppUser.phone_number,
            WhatsAppUser.display_name,
            func.count(ConversationMessage.id).label("messages_count"),
            func.max(ConversationMessage.created_at).label("last_message_at"),
        )
        .join(ConversationMessage, ConversationMessage.user_id == WhatsAppUser.id)
        .group_by(WhatsAppUser.id, WhatsAppUser.phone_number, WhatsAppUser.display_name)
        .order_by(desc(func.max(ConversationMessage.created_at)))
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "user_id": row.id,
            "phone_number": row.phone_number,
            "display_name": row.display_name or "-",
            "messages_count": int(row.messages_count or 0),
            "last_message_at": row.last_message_at,
        }
        for row in rows
    ]


async def list_messages_for_user(
    session: AsyncSession,
    user_id: int,
    limit: int = 500,
) -> List[ConversationMessage]:
    """Return one user's conversation in chronological order."""
    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.user_id == user_id)
        .order_by(ConversationMessage.created_at.asc())
        .limit(limit)
    )
    rows = await session.scalars(stmt)
    return list(rows.all())
