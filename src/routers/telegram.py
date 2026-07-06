"""Telegram webhook routes."""

from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_db
from src.services.conversation_service import create_conversation_message
from src.services.openai_service import generate_openai_reply
from src.services.telegram_service import (
    extract_incoming_user_messages,
    send_telegram_text,
)
from src.services.user_service import get_or_create_whatsapp_user

router = APIRouter(prefix="/webhook/telegram", tags=["telegram"])


def _telegram_user_key(chat_id: int) -> str:
    return f"tg:{chat_id}"


async def _reply_with_openai_and_log(
    chat_id: int,
    user_id: int,
    user_text: str,
) -> None:
    reply_text = await generate_openai_reply(user_text)
    await send_telegram_text(chat_id, reply_text)


@router.post("")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    if settings.TELEGRAM_WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    try:
        payload: Any = await request.json()
    except Exception:
        body = await request.body()
        print(body.decode("utf-8", errors="replace"))
        return {"message": "ignored"}

    if isinstance(payload, dict):
        print(payload)

    incoming_messages = extract_incoming_user_messages(payload)
    for message in incoming_messages:
        user = await get_or_create_whatsapp_user(
            db,
            phone_number=_telegram_user_key(message.chat_id),
        )

        if message.text:
            await create_conversation_message(
                db,
                user_id=user.id,
                direction="user",
                text=message.text,
                channel="telegram",
            )
            background_tasks.add_task(
                _reply_with_openai_and_log,
                message.chat_id,
                user.id,
                message.text,
            )
            continue

        if message.document_file_id or message.voice_file_id:
            background_tasks.add_task(
                send_telegram_text,
                message.chat_id,
                "PDF resume and voice notes are not supported on Telegram yet. Please send text for now.",
            )

    return {"message": "ok"}
