"""Telegram webhook routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.db import SessionLocal, get_db
from src.models.chat_user import ChatUser
from src.services.conversation_service import create_conversation_message
from src.services.job_flow_service import (
    OPPORTUNITY_STAGE_AWAITING_TYPE,
    append_opportunity_cta,
    is_awaiting_opportunity_choice,
    is_opportunity_request,
    normalize_opportunity_type,
    opportunities_reply_for_user,
)
from src.services.openai_service import (
    extract_full_name_from_resume,
    extract_full_name_from_resume_pdf,
    extract_skills_from_resume,
    extract_skills_from_resume_pdf,
    generate_openai_reply,
    transcribe_audio_to_text,
)
from src.services.resume_service import extract_text_from_pdf
from src.services.skill_service import list_skills, set_user_skills_by_names
from src.services.telegram_service import (
    IncomingTelegramMessage,
    download_telegram_file,
    extract_incoming_user_messages,
    send_telegram_text,
)
from src.services.user_service import (
    get_or_create_chat_user,
    save_user_resume_pdf,
    update_user_display_name,
    update_user_job_search_preferences,
)

router = APIRouter(prefix="/webhook/telegram", tags=["telegram"])

_ASK_EDUCATION_OR_JOBS = (
    "I can suggest opportunities matched to your skills. "
    "Do you want education or jobs?"
)
_ASK_PDF_RESUME = "Hello! Before we start, please send your CV resume as a PDF file."
_CV_THANKS_TEMPLATE = (
    "Thanks, your CV is uploaded. "
    "Extracted skills: {skills}. "
    "What are you looking for — education opportunities or job opportunities? "
    "Reply with education or jobs."
)


def _telegram_user_key(chat_id: int) -> str:
    return f"tg:{chat_id}"


def _verify_webhook_secret(request: Request) -> None:
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        return
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")


def _queue_reply(
    background_tasks: BackgroundTasks,
    chat_id: int,
    user_id: int,
    body: str,
) -> None:
    background_tasks.add_task(_send_and_log_text, chat_id, user_id, body)


def _queue_opportunities(
    background_tasks: BackgroundTasks,
    chat_id: int,
    user_id: int,
    opportunity_type: str,
    request_text: str,
) -> None:
    background_tasks.add_task(
        _list_opportunities_and_log,
        chat_id,
        user_id,
        opportunity_type,
        request_text,
    )


def _queue_openai_chat(
    background_tasks: BackgroundTasks,
    chat_id: int,
    user_id: int,
    user_text: str,
) -> None:
    background_tasks.add_task(_reply_with_openai_and_log, chat_id, user_id, user_text)


async def _set_opportunity_stage(
    db: AsyncSession,
    user: ChatUser,
    stage: Optional[str],
) -> None:
    await update_user_job_search_preferences(
        db,
        user,
        job_search_stage=stage,
        preferred_work_mode=None,
        preferred_job_location=None,
    )


async def _send_and_log_text(chat_id: int, user_id: int, body: str) -> None:
    sent_body = await send_telegram_text(chat_id, body)
    async with SessionLocal() as session:
        await create_conversation_message(
            session,
            user_id=user_id,
            direction="assistant",
            text=sent_body,
            channel="telegram",
        )


async def _reply_with_openai_and_log(
    chat_id: int,
    user_id: int,
    user_text: str,
) -> None:
    reply_text = await generate_openai_reply(user_text)
    async with SessionLocal() as session:
        user = await session.scalar(
            select(ChatUser)
            .options(selectinload(ChatUser.skills))
            .where(ChatUser.id == user_id)
        )
    if user and user.skills:
        reply_text = append_opportunity_cta(reply_text)
    await _send_and_log_text(chat_id, user_id, reply_text)


async def _list_opportunities_and_log(
    chat_id: int,
    user_id: int,
    opportunity_type: str,
    request_text: Optional[str] = None,
) -> None:
    async with SessionLocal() as session:
        reply_text = await opportunities_reply_for_user(
            session,
            user_id=user_id,
            opportunity_type=opportunity_type,
            request_text=request_text,
        )
    await _send_and_log_text(chat_id, user_id, reply_text)


async def _handle_cv_document(
    db: AsyncSession,
    user: ChatUser,
    message: IncomingTelegramMessage,
    background_tasks: BackgroundTasks,
) -> None:
    """Download CV PDF, extract skills/name, then ask education vs jobs."""
    chat_id = message.chat_id
    if message.document_mime_type != "application/pdf":
        _queue_reply(background_tasks, chat_id, user.id, "Please send your resume as a PDF file.")
        return

    pdf_bytes = await download_telegram_file(message.document_file_id or "")
    if not pdf_bytes:
        _queue_reply(
            background_tasks,
            chat_id,
            user.id,
            "I could not download your resume right now. Please send the PDF again.",
        )
        return

    await save_user_resume_pdf(db, user, pdf_bytes)

    resume_text = extract_text_from_pdf(pdf_bytes)
    canonical_skill_names = [skill.name for skill in await list_skills(db)]
    if resume_text.strip():
        extracted_full_name = await extract_full_name_from_resume(resume_text)
        matched_skill_names = await extract_skills_from_resume(
            resume_text,
            canonical_skill_names,
        )
    else:
        extracted_full_name = await extract_full_name_from_resume_pdf(pdf_bytes)
        matched_skill_names = await extract_skills_from_resume_pdf(
            pdf_bytes,
            canonical_skill_names,
        )

    if extracted_full_name:
        await update_user_display_name(db, user, extracted_full_name)

    matched_skills = await set_user_skills_by_names(db, user, matched_skill_names)
    skills_text = ", ".join(skill.name for skill in matched_skills) or "none"

    await _set_opportunity_stage(db, user, OPPORTUNITY_STAGE_AWAITING_TYPE)
    _queue_reply(
        background_tasks,
        chat_id,
        user.id,
        _CV_THANKS_TEMPLATE.format(skills=skills_text),
    )


async def _handle_user_utterance(
    db: AsyncSession,
    user: ChatUser,
    text: str,
    background_tasks: BackgroundTasks,
    chat_id: int,
    *,
    unclear_awaiting_reply: str,
    allow_vague_opportunity_request: bool,
) -> None:
    """Route education/jobs choice or fall back to general OpenAI chat."""
    opportunity_type = normalize_opportunity_type(text)
    awaiting = is_awaiting_opportunity_choice(user.job_search_stage)

    if awaiting:
        if not opportunity_type:
            await _set_opportunity_stage(db, user, OPPORTUNITY_STAGE_AWAITING_TYPE)
            _queue_reply(background_tasks, chat_id, user.id, unclear_awaiting_reply)
            return
        await _set_opportunity_stage(db, user, None)
        _queue_opportunities(background_tasks, chat_id, user.id, opportunity_type, text)
        return

    if opportunity_type or (allow_vague_opportunity_request and is_opportunity_request(text)):
        if opportunity_type:
            await _set_opportunity_stage(db, user, None)
            _queue_opportunities(background_tasks, chat_id, user.id, opportunity_type, text)
            return
        await _set_opportunity_stage(db, user, OPPORTUNITY_STAGE_AWAITING_TYPE)
        _queue_reply(background_tasks, chat_id, user.id, _ASK_EDUCATION_OR_JOBS)
        return

    _queue_openai_chat(background_tasks, chat_id, user.id, text)


async def _handle_voice_note(
    db: AsyncSession,
    user: ChatUser,
    voice_file_id: str,
    background_tasks: BackgroundTasks,
    chat_id: int,
) -> None:
    voice_bytes = await download_telegram_file(voice_file_id)
    if not voice_bytes:
        _queue_reply(
            background_tasks,
            chat_id,
            user.id,
            "I could not download your audio right now. Please try again.",
        )
        return

    transcript = await transcribe_audio_to_text(voice_bytes, "audio/ogg")
    if not transcript:
        _queue_reply(
            background_tasks,
            chat_id,
            user.id,
            "I could not understand your audio. Please send a clearer voice note or text.",
        )
        return

    # Voice: only enter opportunity flow for a clear type or while awaiting a choice.
    await _handle_user_utterance(
        db,
        user,
        transcript,
        background_tasks,
        chat_id,
        unclear_awaiting_reply=(
            "Please say education or jobs so I can list matching opportunities."
        ),
        allow_vague_opportunity_request=False,
    )


async def _process_incoming_message(
    db: AsyncSession,
    message: IncomingTelegramMessage,
    background_tasks: BackgroundTasks,
) -> None:
    user = await get_or_create_chat_user(
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

    if message.document_file_id:
        await _handle_cv_document(db, user, message, background_tasks)
        return

    if not user.resume_pdf:
        _queue_reply(background_tasks, message.chat_id, user.id, _ASK_PDF_RESUME)
        return

    if message.voice_file_id:
        await _handle_voice_note(
            db,
            user,
            message.voice_file_id,
            background_tasks,
            message.chat_id,
        )
        return

    if not message.text:
        return

    await _handle_user_utterance(
        db,
        user,
        message.text.strip(),
        background_tasks,
        message.chat_id,
        unclear_awaiting_reply="Please reply with one option: education or jobs.",
        allow_vague_opportunity_request=True,
    )


@router.post("")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    _verify_webhook_secret(request)

    try:
        payload: Any = await request.json()
    except Exception:
        body = await request.body()
        print(body.decode("utf-8", errors="replace"))
        return {"message": "ignored"}

    if isinstance(payload, dict):
        print(payload)

    for message in extract_incoming_user_messages(payload):
        await _process_incoming_message(db, message, background_tasks)

    return {"message": "ok"}
