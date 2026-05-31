"""WhatsApp webhook routes."""

from typing import Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_db
from src.services.openai_service import (
    extract_skills_from_resume,
    generate_openai_reply,
    transcribe_audio_to_text,
)
from src.services.resume_service import extract_text_from_pdf
from src.services.skill_service import list_skills, set_user_skills_by_names
from src.services.user_service import get_or_create_whatsapp_user, save_user_resume_pdf
from src.services.whatsapp_service import (
    download_whatsapp_media,
    extract_incoming_user_messages,
    send_whatsapp_text,
)

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
        reply_phone_number_id = message.phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        if not reply_phone_number_id:
            print("WHATSAPP_PHONE_NUMBER_ID is missing; cannot send outbound WhatsApp messages.")
            continue

        # Ensure every sender exists in DB; unique key is phone_number.
        user = await get_or_create_whatsapp_user(db, phone_number=message.from_wa_id)

        if message.document_id:
            if message.document_mime_type != "application/pdf":
                background_tasks.add_task(
                    send_whatsapp_text,
                    reply_phone_number_id,
                    message.from_wa_id,
                    "Please send your resume as a PDF file.",
                )
                continue

            pdf_bytes = await download_whatsapp_media(message.document_id)
            if not pdf_bytes:
                background_tasks.add_task(
                    send_whatsapp_text,
                    reply_phone_number_id,
                    message.from_wa_id,
                    "I could not download your resume right now. Please send the PDF again.",
                )
                continue

            await save_user_resume_pdf(db, user, pdf_bytes)

            resume_text = extract_text_from_pdf(pdf_bytes)
            skills = await list_skills(db)
            canonical_skill_names = [skill.name for skill in skills]
            matched_skill_names = await extract_skills_from_resume(resume_text, canonical_skill_names)
            matched_skills = await set_user_skills_by_names(db, user, matched_skill_names)
            skills_text = ", ".join(skill.name for skill in matched_skills) or "none"

            background_tasks.add_task(
                send_whatsapp_text,
                reply_phone_number_id,
                message.from_wa_id,
                f"Thanks, your CV is uploaded. Extracted skills: {skills_text}. You can now send your questions.",
            )
            continue

        if not user.resume_pdf:
            background_tasks.add_task(
                send_whatsapp_text,
                reply_phone_number_id,
                message.from_wa_id,
                "Before we start, please send your CV resume as a PDF file.",
            )
            continue

        if message.audio_id:
            audio_bytes = await download_whatsapp_media(message.audio_id)
            if not audio_bytes:
                background_tasks.add_task(
                    send_whatsapp_text,
                    reply_phone_number_id,
                    message.from_wa_id,
                    "I could not download your audio right now. Please try again.",
                )
                continue

            transcript = await transcribe_audio_to_text(audio_bytes, message.audio_mime_type)
            if not transcript:
                background_tasks.add_task(
                    send_whatsapp_text,
                    reply_phone_number_id,
                    message.from_wa_id,
                    "I could not understand your audio. Please send a clearer voice note or text.",
                )
                continue

            background_tasks.add_task(
                _reply_with_openai,
                reply_phone_number_id,
                message.from_wa_id,
                transcript,
            )
            continue

        if not message.text:
            continue

        background_tasks.add_task(
            _reply_with_openai,
            reply_phone_number_id,
            message.from_wa_id,
            message.text,
        )

    return {"message": "ok"}
