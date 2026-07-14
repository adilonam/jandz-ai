"""Telegram webhook routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.db import SessionLocal, get_db
from src.models.whatsapp_user import WhatsAppUser
from src.routers.whatsapp import (
    JOB_STAGE_AWAITING_LOCATION,
    JOB_STAGE_AWAITING_WORK_MODE,
    _append_job_search_cta,
    _clean_location_candidate,
    _is_job_search_request,
    _normalize_work_mode,
    _resolve_location_text,
    _search_jobs_reply_for_user,
)
from src.services.conversation_service import create_conversation_message
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
    download_telegram_file,
    extract_incoming_user_messages,
    send_telegram_text,
)
from src.services.user_service import (
    get_or_create_whatsapp_user,
    save_user_resume_pdf,
    update_user_display_name,
    update_user_job_search_preferences,
)

router = APIRouter(prefix="/webhook/telegram", tags=["telegram"])


def _telegram_user_key(chat_id: int) -> str:
    return f"tg:{chat_id}"


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
            select(WhatsAppUser)
            .options(selectinload(WhatsAppUser.skills))
            .where(WhatsAppUser.id == user_id)
        )
    if user and user.skills:
        reply_text = _append_job_search_cta(reply_text)
    await _send_and_log_text(chat_id, user_id, reply_text)


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

        if message.document_file_id:
            if message.document_mime_type != "application/pdf":
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "Please send your resume as a PDF file.",
                )
                continue

            pdf_bytes = await download_telegram_file(message.document_file_id)
            if not pdf_bytes:
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "I could not download your resume right now. Please send the PDF again.",
                )
                continue

            await save_user_resume_pdf(db, user, pdf_bytes)

            resume_text = extract_text_from_pdf(pdf_bytes)
            extracted_full_name: Optional[str] = None
            if resume_text.strip():
                extracted_full_name = await extract_full_name_from_resume(resume_text)
            else:
                extracted_full_name = await extract_full_name_from_resume_pdf(pdf_bytes)

            if extracted_full_name:
                await update_user_display_name(db, user, extracted_full_name)

            skills = await list_skills(db)
            canonical_skill_names = [skill.name for skill in skills]
            if resume_text.strip():
                matched_skill_names = await extract_skills_from_resume(
                    resume_text,
                    canonical_skill_names,
                )
            else:
                matched_skill_names = await extract_skills_from_resume_pdf(
                    pdf_bytes,
                    canonical_skill_names,
                )
            matched_skills = await set_user_skills_by_names(db, user, matched_skill_names)
            skills_text = ", ".join(skill.name for skill in matched_skills) or "none"

            await update_user_job_search_preferences(
                db,
                user,
                job_search_stage=JOB_STAGE_AWAITING_WORK_MODE,
                preferred_work_mode=None,
                preferred_job_location=None,
            )

            background_tasks.add_task(
                _send_and_log_text,
                message.chat_id,
                user.id,
                "Thanks, your CV is uploaded. "
                f"Extracted skills: {skills_text}. "
                "Do you want remote or onsite jobs?",
            )
            continue

        if not user.resume_pdf:
            background_tasks.add_task(
                _send_and_log_text,
                message.chat_id,
                user.id,
                "Hello! Before we start, please send your CV resume as a PDF file.",
            )
            continue

        if message.voice_file_id:
            voice_bytes = await download_telegram_file(message.voice_file_id)
            if not voice_bytes:
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "I could not download your audio right now. Please try again.",
                )
                continue

            transcript = await transcribe_audio_to_text(voice_bytes, "audio/ogg")
            if not transcript:
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "I could not understand your audio. Please send a clearer voice note or text.",
                )
                continue

            background_tasks.add_task(
                _reply_with_openai_and_log,
                message.chat_id,
                user.id,
                transcript,
            )
            continue

        if not message.text:
            continue

        incoming_text = message.text.strip()
        if _is_job_search_request(incoming_text):
            requested_work_mode = _normalize_work_mode(incoming_text) or user.preferred_work_mode
            requested_location = (
                _resolve_location_text(incoming_text) or user.preferred_job_location
            )
            if requested_location:
                requested_location = (
                    _clean_location_candidate(requested_location) or requested_location
                )

            if requested_work_mode and requested_location:
                await update_user_job_search_preferences(
                    db,
                    user,
                    job_search_stage=None,
                    preferred_work_mode=requested_work_mode,
                    preferred_job_location=requested_location,
                )
                jobs_reply = await _search_jobs_reply_for_user(
                    db,
                    user_id=user.id,
                    requested_text=incoming_text,
                    work_mode=requested_work_mode,
                    location=requested_location,
                )
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    jobs_reply,
                )
                continue

            if requested_work_mode and not requested_location:
                await update_user_job_search_preferences(
                    db,
                    user,
                    job_search_stage=JOB_STAGE_AWAITING_LOCATION,
                    preferred_work_mode=requested_work_mode,
                    preferred_job_location=None,
                )
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "Please share your target job location (city or country).",
                )
                continue

            if not requested_work_mode and requested_location:
                await update_user_job_search_preferences(
                    db,
                    user,
                    job_search_stage=JOB_STAGE_AWAITING_WORK_MODE,
                    preferred_work_mode=None,
                    preferred_job_location=requested_location,
                )
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "Do you prefer remote or onsite roles?",
                )
                continue

            await update_user_job_search_preferences(
                db,
                user,
                job_search_stage=JOB_STAGE_AWAITING_WORK_MODE,
                preferred_work_mode=None,
                preferred_job_location=None,
            )
            background_tasks.add_task(
                _send_and_log_text,
                message.chat_id,
                user.id,
                "I can search jobs for you now. Do you want remote or onsite jobs, and what location?",
            )
            continue

        if user.job_search_stage == JOB_STAGE_AWAITING_WORK_MODE:
            work_mode = _normalize_work_mode(message.text)
            if not work_mode:
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "Please answer with one option: remote or onsite.",
                )
                continue

            await update_user_job_search_preferences(
                db,
                user,
                job_search_stage=JOB_STAGE_AWAITING_LOCATION,
                preferred_work_mode=work_mode,
                preferred_job_location=None,
            )
            background_tasks.add_task(
                _send_and_log_text,
                message.chat_id,
                user.id,
                "Great. What city or area are you targeting for the job search?",
            )
            continue

        if user.job_search_stage == JOB_STAGE_AWAITING_LOCATION:
            location = _resolve_location_text(message.text) or message.text.strip()
            if len(location) < 2:
                background_tasks.add_task(
                    _send_and_log_text,
                    message.chat_id,
                    user.id,
                    "Please send a valid location (for example: Casablanca, Rabat, or Paris).",
                )
                continue

            work_mode = user.preferred_work_mode or "remote"

            await update_user_job_search_preferences(
                db,
                user,
                job_search_stage=None,
                preferred_work_mode=work_mode,
                preferred_job_location=location,
            )
            jobs_reply = await _search_jobs_reply_for_user(
                db,
                user_id=user.id,
                requested_text=message.text,
                work_mode=work_mode,
                location=location,
            )

            background_tasks.add_task(
                _send_and_log_text,
                message.chat_id,
                user.id,
                jobs_reply,
            )
            continue

        background_tasks.add_task(
            _reply_with_openai_and_log,
            message.chat_id,
            user.id,
            message.text,
        )

    return {"message": "ok"}
