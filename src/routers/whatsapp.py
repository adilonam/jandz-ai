"""WhatsApp webhook routes."""

from typing import Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_db
from src.services.openai_service import generate_openai_reply
from src.services.user_service import get_or_create_whatsapp_user
from src.services.whatsapp_service import extract_incoming_user_messages, send_whatsapp_text

router = APIRouter(prefix="/webhook/whatsapp", tags=["whatsapp"])


def _query(request: Request, dotted: str, underscored: str) -> Optional[str]:
    """Meta sends hub.mode / hub.challenge / hub.verify_token; some clients duplicate as hub_mode."""
    query = request.query_params
    return query.get(dotted) or query.get(underscored)


async def _reply_with_openai(phone_number_id: str, from_id: str, incoming_text: str) -> None:
    reply_text = await generate_openai_reply(incoming_text)
    await send_whatsapp_text(phone_number_id, from_id, reply_text)


@router.get("")
async def whatsapp_verify(request: Request) -> Response:
    mode = _query(request, "hub.mode", "hub_mode")
    token = _query(request, "hub.verify_token", "hub_verify_token")
    challenge = _query(request, "hub.challenge", "hub_challenge")

    if mode == "subscribe" and challenge:
        if settings.WHATSAPP_VERIFY_TOKEN and token == settings.WHATSAPP_VERIFY_TOKEN:
            return PlainTextResponse(content=challenge)
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    try:
        payload = await request.json()
    except Exception:
        body = await request.body()
        print(body.decode("utf-8", errors="replace"))
        return {"message": "ignored"}

    if isinstance(payload, dict):
        print(payload)

    incoming_messages = extract_incoming_user_messages(payload)
    for message in incoming_messages:
        # Ensure every sender exists in DB; unique key is phone_number.
        await get_or_create_whatsapp_user(db, phone_number=message.from_wa_id)
        background_tasks.add_task(
            _reply_with_openai,
            message.phone_number_id,
            message.from_wa_id,
            message.text,
        )

    return {"message": "ok"}
