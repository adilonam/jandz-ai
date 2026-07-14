"""WhatsApp webhook routes."""

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.db import SessionLocal, get_db
from src.models.whatsapp_user import WhatsAppUser
from src.services.conversation_service import create_conversation_message
from src.services.coresignal_service import search_jobs
from src.services.job_search_history_service import create_job_search_history
from src.services.openai_service import (
    extract_full_name_from_resume,
    extract_full_name_from_resume_pdf,
    extract_skills_from_resume_pdf,
    extract_skills_from_resume,
    generate_openai_reply,
    transcribe_audio_to_text,
)
from src.services.resume_service import extract_text_from_pdf
from src.services.skill_service import list_skills, set_user_skills_by_names
from src.services.user_service import (
    get_or_create_whatsapp_user,
    save_user_resume_pdf,
    update_user_display_name,
    update_user_job_search_preferences,
)
from src.services.whatsapp_service import (
    download_whatsapp_media,
    extract_incoming_user_messages,
    send_whatsapp_text,
)

router = APIRouter(prefix="/webhook/whatsapp", tags=["whatsapp"])

JOB_STAGE_AWAITING_WORK_MODE = "awaiting_work_mode"
JOB_STAGE_AWAITING_LOCATION = "awaiting_location"
JOB_ASSISTANT_CTA = (
    " I am an AI assistant and I can help you with job search. "
    "Do you want remote or onsite jobs? Please share your location."
)


def _normalize_work_mode(text: str) -> Optional[str]:
    normalized = text.strip().lower()
    if not normalized:
        return None
    if any(word in normalized for word in {"remote", "remotely", "work from home", "wfh"}):
        return "remote"
    if any(word in normalized for word in {"onsite", "on-site", "on site", "office", "in office"}):
        return "onsite"
    return None


def _is_job_search_request(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    keywords = {
        "job",
        "jobs",
        "position",
        "positions",
        "opening",
        "openings",
        "hiring",
        "vacancy",
        "vacancies",
        "work",
    }
    return any(word in normalized for word in keywords)


# Tokens that must not be treated as (or keep trailing after) a place name.
_LOCATION_STOP_WORDS = frozenset(
    {
        "remote",
        "remotely",
        "onsite",
        "on-site",
        "hybrid",
        "wfh",
        "office",
        "job",
        "jobs",
        "position",
        "positions",
        "role",
        "roles",
        "opening",
        "openings",
        "vacancy",
        "vacancies",
        "hiring",
        "work",
        "working",
        "for",
        "with",
        "and",
        "as",
        "or",
        "the",
        "a",
        "an",
        "my",
        "me",
        "please",
        "looking",
        "want",
        "need",
        "get",
        "give",
        "find",
        "search",
        "seeking",
        "python",
        "java",
        "javascript",
        "typescript",
        "golang",
        "rust",
        "kotlin",
        "devops",
        "frontend",
        "backend",
        "fullstack",
        "full-stack",
        "data",
        "ai",
        "ml",
        "product",
        "manager",
        "engineer",
        "engineering",
        "developer",
        "designer",
        "scientist",
        "analyst",
        "nurse",
        "teacher",
        "senior",
        "junior",
        "lead",
        "software",
        "marketing",
        "sales",
        "intern",
        "internship",
    }
)

# Map place names / demonyms to CoreSignal country values and ISO-ish codes.
_COUNTRY_ALIASES = {
    "france": frozenset({"france", "fr", "fra", "french"}),
    "germany": frozenset({"germany", "de", "deu", "deutschland", "german"}),
    "morocco": frozenset({"morocco", "ma", "mar", "maroc", "moroccan"}),
    "spain": frozenset({"spain", "es", "esp", "españa", "espana", "spanish"}),
    "italy": frozenset({"italy", "it", "ita", "italia", "italian"}),
    "portugal": frozenset({"portugal", "pt", "prt", "portuguese"}),
    "netherlands": frozenset({"netherlands", "nl", "nld", "holland", "dutch"}),
    "belgium": frozenset({"belgium", "be", "bel", "belgian"}),
    "switzerland": frozenset({"switzerland", "ch", "che", "swiss"}),
    "canada": frozenset({"canada", "ca", "can", "canadian"}),
    "united kingdom": frozenset({"united kingdom", "uk", "gb", "gbr", "britain", "england"}),
    "uk": frozenset({"united kingdom", "uk", "gb", "gbr", "britain", "england"}),
    "united states": frozenset({"united states", "usa", "us", "america", "american"}),
    "usa": frozenset({"united states", "usa", "us", "america", "american"}),
    "us": frozenset({"united states", "usa", "us", "america", "american"}),
}


def _clean_location_candidate(raw: str) -> Optional[str]:
    """Keep leading place tokens; drop work-mode / role / filler trailing words."""
    if not raw:
        return None

    tokens = re.findall(r"[A-Za-z][A-Za-z\-']*", raw.strip(" .,!?:;"))
    kept: List[str] = []
    for token in tokens:
        lower = token.lower()
        if lower in _LOCATION_STOP_WORDS:
            if kept:
                break
            continue
        kept.append(token)

    location = " ".join(kept).strip()
    return location or None


def _extract_location_from_text(text: str) -> Optional[str]:
    normalized = text.strip()
    if not normalized:
        return None

    match = re.search(
        r"\b(?:in|at|near|from)\s+([A-Za-z][A-Za-z\s\-']{1,60})",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None

    return _clean_location_candidate(match.group(1))


def _resolve_location_text(text: str) -> Optional[str]:
    """Prefer explicit 'in/at/near/from' phrases; otherwise clean free-text location."""
    return _extract_location_from_text(text) or _clean_location_candidate(text.strip())


def _infer_query_term(requested_text: str, skill_names: List[str]) -> str:
    lowered = requested_text.lower()
    preferred_phrases = [
        ("product manager", "Product Manager"),
        ("project manager", "Project Manager"),
        ("software engineer", "Software Engineer"),
        ("data scientist", "Data Scientist"),
        ("data engineer", "Data Engineer"),
        ("machine learning", "Machine Learning"),
        ("full stack", "Full Stack"),
        ("fullstack", "Full Stack"),
    ]
    for phrase, label in preferred_phrases:
        if phrase in lowered:
            return label

    preferred_terms = [
        "python",
        "javascript",
        "typescript",
        "java",
        "golang",
        "devops",
        "nurse",
        "teacher",
        "designer",
        "data",
    ]
    for term in preferred_terms:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            return term.title()

    for skill_name in skill_names:
        clean = skill_name.strip()
        if clean:
            return clean

    return "Software Engineer"


def _matches_work_mode(row: Dict[str, Any], work_mode: str) -> bool:
    accepts_remote = row.get("accepts_remote")
    text_blob = " ".join(
        [
            str(row.get("title") or ""),
            str(row.get("description") or ""),
            str(row.get("location") or ""),
            str(row.get("employment_type") or ""),
        ]
    ).lower()

    if work_mode == "remote":
        if accepts_remote is True:
            return True
        if accepts_remote is False:
            return False
        # Flag missing: keep unless clearly onsite-only (API may already have filtered).
        if "onsite" in text_blob or "on-site" in text_blob:
            return False
        return True

    if work_mode == "onsite":
        if accepts_remote is True and "onsite" not in text_blob and "on-site" not in text_blob:
            return False
        if "remote" in text_blob and "onsite" not in text_blob and "on-site" not in text_blob:
            return False
        return True

    return True


def _place_match_tokens(location: str) -> List[str]:
    cleaned = _clean_location_candidate(location) or location.strip()
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z\-']*", cleaned)]


def _matches_requested_country(row: Dict[str, Any], location: str) -> bool:
    tokens = _place_match_tokens(location)
    if not tokens:
        return True

    row_location = str(row.get("location") or "").lower()
    row_country = str(row.get("country") or "").lower()
    row_city = str(row.get("city") or "").lower()
    haystack = f"{row_location} {row_country} {row_city}".strip()
    requested_phrase = " ".join(tokens)

    if requested_phrase and requested_phrase in haystack:
        return True

    alias_keys = [requested_phrase, *tokens]
    for key in alias_keys:
        aliases = _COUNTRY_ALIASES.get(key)
        if not aliases:
            continue
        if row_country in aliases:
            return True
        if any(alias in haystack for alias in aliases if len(alias) >= 2):
            return True

    for token in tokens:
        if len(token) >= 2 and token in haystack:
            return True

    return False


def _format_filtered_jobs_reply(
    jobs: List[Dict[str, Any]],
    location: str,
    work_mode: str,
    limit: Optional[int] = None,
) -> str:
    max_jobs = limit if limit is not None else settings.JOBS_TO_SHOW
    display_location = _clean_location_candidate(location) or location.strip()
    location_lower = display_location.lower().strip()

    def score(row: Dict[str, Any]) -> int:
        row_location = " ".join(
            [
                str(row.get("location") or ""),
                str(row.get("country") or ""),
                str(row.get("city") or ""),
            ]
        ).lower()
        score_value = 0
        if location_lower and (
            location_lower in row_location or _matches_requested_country(row, display_location)
        ):
            score_value += 3
        if _matches_work_mode(row, work_mode):
            score_value += 1
        return score_value

    sorted_rows = sorted(jobs, key=score, reverse=True)
    picked: List[Dict[str, Any]] = []
    for row in sorted_rows:
        if not _matches_requested_country(row, display_location):
            continue
        if not _matches_work_mode(row, work_mode):
            continue
        picked.append(row)
        if len(picked) >= max_jobs:
            break

    if not picked:
        return (
            f"I could not find matching {work_mode} jobs in {display_location} right now. "
            "Please try a nearby city/country or another role keyword."
        )

    lines = [f"Here are {len(picked)} matching {work_mode} job opportunities:"]
    for idx, row in enumerate(picked, start=1):
        title = str(row.get("title") or "Untitled role").strip()
        company = str(row.get("company_name") or "Unknown company").strip()
        row_location = str(row.get("location") or row.get("country") or "Unknown location").strip()
        url = str(row.get("url") or row.get("external_url") or "").strip()

        line = f"{idx}. {title} - {company} - {row_location}"
        if url:
            line = f"{line} - {url}"
        lines.append(line)

    return "\n".join(lines)


def _append_job_search_cta(reply_text: str) -> str:
    if JOB_ASSISTANT_CTA.lower() in reply_text.lower():
        return reply_text
    return f"{reply_text.rstrip()}{JOB_ASSISTANT_CTA}"


def _query(request: Request, dotted: str, underscored: str) -> Optional[str]:
    """Meta sends hub.mode / hub.challenge / hub.verify_token; some clients duplicate as hub_mode."""
    query = request.query_params
    return query.get(dotted) or query.get(underscored)


async def _reply_with_openai(phone_number_id: str, from_id: str, incoming_text: str) -> None:
    reply_text = await generate_openai_reply(incoming_text)
    await send_whatsapp_text(phone_number_id, from_id, reply_text)


async def _send_and_log_text(
    phone_number_id: str,
    from_id: str,
    user_id: int,
    body: str,
) -> None:
    sent_body = await send_whatsapp_text(phone_number_id, from_id, body)
    async with SessionLocal() as session:
        await create_conversation_message(
            session,
            user_id=user_id,
            direction="assistant",
            text=sent_body,
            channel="whatsapp",
        )


async def _reply_with_openai_and_log(
    phone_number_id: str,
    from_id: str,
    user_id: int,
    incoming_text: str,
) -> None:
    reply_text = await generate_openai_reply(incoming_text)
    async with SessionLocal() as session:
        user = await session.scalar(
            select(WhatsAppUser)
            .options(selectinload(WhatsAppUser.skills))
            .where(WhatsAppUser.id == user_id)
        )
    if user and user.skills:
        reply_text = _append_job_search_cta(reply_text)
    await _send_and_log_text(phone_number_id, from_id, user_id, reply_text)


async def _search_jobs_reply_for_user(
    db: AsyncSession,
    user_id: int,
    requested_text: str,
    work_mode: str,
    location: str,
) -> str:
    user = await db.scalar(
        select(WhatsAppUser)
        .options(selectinload(WhatsAppUser.skills))
        .where(WhatsAppUser.id == user_id)
    )
    if not user:
        return "I could not find your profile. Please send your CV PDF again."

    skill_names = [skill.name for skill in user.skills]
    query_term = _infer_query_term(requested_text, skill_names)
    clean_location = _clean_location_candidate(location) or location.strip()
    prompt_query = (
        f"title={query_term}; location={clean_location}; work_mode={work_mode}; "
        f"skills={', '.join(skill_names) if skill_names else 'general profile'}"
    )
    try:
        result = await search_jobs(
            title=query_term,
            location=clean_location,
            work_mode=work_mode,
            limit=max(20, settings.JOBS_TO_SHOW),
        )
        await create_job_search_history(
            db,
            prompt_query=prompt_query,
            response_payload=result["history_payload"],
            provider="coresignal_api",
        )
        jobs = result.get("jobs") or []
        if not jobs:
            return (
                f"I could not find matching {work_mode} jobs in {clean_location} right now. "
                "Please try a nearby city/country or another role keyword."
            )
        return _format_filtered_jobs_reply(
            jobs,
            location=clean_location,
            work_mode=work_mode,
            limit=settings.JOBS_TO_SHOW,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"CoreSignal search failed: {exc}")
        return "I could not search jobs right now. Please try again in a moment."


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

        if message.text:
            await create_conversation_message(
                db,
                user_id=user.id,
                direction="user",
                text=message.text,
                channel="whatsapp",
            )

        if message.document_id:
            if message.document_mime_type != "application/pdf":
                background_tasks.add_task(
                    _send_and_log_text,
                    reply_phone_number_id,
                    message.from_wa_id,
                    user.id,
                    "Please send your resume as a PDF file.",
                )
                continue

            pdf_bytes = await download_whatsapp_media(message.document_id)
            if not pdf_bytes:
                background_tasks.add_task(
                    _send_and_log_text,
                    reply_phone_number_id,
                    message.from_wa_id,
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
                reply_phone_number_id,
                message.from_wa_id,
                user.id,
                "Thanks, your CV is uploaded. "
                f"Extracted skills: {skills_text}. "
                "Do you want remote or onsite jobs?",
            )
            continue

        if not user.resume_pdf:
            background_tasks.add_task(
                _send_and_log_text,
                reply_phone_number_id,
                message.from_wa_id,
                user.id,
                "Before we start, please send your CV resume as a PDF file.",
            )
            continue

        if message.audio_id:
            audio_bytes = await download_whatsapp_media(message.audio_id)
            if not audio_bytes:
                background_tasks.add_task(
                    _send_and_log_text,
                    reply_phone_number_id,
                    message.from_wa_id,
                    user.id,
                    "I could not download your audio right now. Please try again.",
                )
                continue

            transcript = await transcribe_audio_to_text(audio_bytes, message.audio_mime_type)
            if not transcript:
                background_tasks.add_task(
                    _send_and_log_text,
                    reply_phone_number_id,
                    message.from_wa_id,
                    user.id,
                    "I could not understand your audio. Please send a clearer voice note or text.",
                )
                continue

            background_tasks.add_task(
                _reply_with_openai_and_log,
                reply_phone_number_id,
                message.from_wa_id,
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
                    reply_phone_number_id,
                    message.from_wa_id,
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
                    reply_phone_number_id,
                    message.from_wa_id,
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
                    reply_phone_number_id,
                    message.from_wa_id,
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
                reply_phone_number_id,
                message.from_wa_id,
                user.id,
                "I can search jobs for you now. Do you want remote or onsite jobs, and what location?",
            )
            continue

        if user.job_search_stage == JOB_STAGE_AWAITING_WORK_MODE:
            work_mode = _normalize_work_mode(message.text)
            if not work_mode:
                background_tasks.add_task(
                    _send_and_log_text,
                    reply_phone_number_id,
                    message.from_wa_id,
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
                reply_phone_number_id,
                message.from_wa_id,
                user.id,
                "Great. What city or area are you targeting for the job search?",
            )
            continue

        if user.job_search_stage == JOB_STAGE_AWAITING_LOCATION:
            location = _resolve_location_text(message.text) or message.text.strip()
            if len(location) < 2:
                background_tasks.add_task(
                    _send_and_log_text,
                    reply_phone_number_id,
                    message.from_wa_id,
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
                reply_phone_number_id,
                message.from_wa_id,
                user.id,
                jobs_reply,
            )
            continue

        background_tasks.add_task(
            _reply_with_openai_and_log,
            reply_phone_number_id,
            message.from_wa_id,
            user.id,
            message.text,
        )

    return {"message": "ok"}
