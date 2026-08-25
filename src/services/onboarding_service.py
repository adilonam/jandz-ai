"""Manual onboarding when a user has no CV."""

import re
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chat_user import ChatUser
from src.models.skill import Skill
from src.services.job_flow_service import OPPORTUNITY_STAGE_AWAITING_TYPE
from src.services.openai_service import generate_manual_cv_content
from src.services.resume_generator_service import generate_cv_pdf
from src.services.skill_service import list_skills, set_user_skills_by_names
from src.services.user_service import (
    get_user_onboarding_data,
    save_user_resume_pdf,
    update_user_display_name,
    update_user_job_search_preferences,
    update_user_onboarding_data,
)

STAGE_AWAITING_CV_CHOICE = "awaiting_cv_choice"
STAGE_MANUAL_AWAITING_NAME = "manual_awaiting_name"
STAGE_MANUAL_AWAITING_CATEGORY = "manual_awaiting_category"
STAGE_MANUAL_AWAITING_SKILLS = "manual_awaiting_skills"

MANUAL_ONBOARDING_STAGES = frozenset(
    {
        STAGE_MANUAL_AWAITING_NAME,
        STAGE_MANUAL_AWAITING_CATEGORY,
        STAGE_MANUAL_AWAITING_SKILLS,
    }
)

_ASK_CV_OR_NO = (
    "Hello! Before we start, please send your CV resume as a PDF file.\n\n"
    "Don't have a CV? Reply *no* and I'll ask a few quick questions to build one for you."
)
_ASK_NAME = "No problem! Let's build your profile.\n\nWhat is your full name?"
_ASK_CATEGORY_TEMPLATE = (
    "Thanks, {name}!\n\n"
    "Which field best describes your background? Reply with the number:\n\n"
    "{options}"
)
_ASK_SKILLS_TEMPLATE = (
    "Great choice: *{category}*\n\n"
    "Pick your skills (reply with numbers separated by commas, e.g. 1,3):\n\n"
    "{options}"
)
_REMIND_CV_OR_NO = (
    "Please send your CV as a PDF file, or reply *no* if you don't have one."
)
_INVALID_NAME = "Please send your full name (at least 2 characters)."
_INVALID_CATEGORY = "Please reply with one of the listed numbers for your field."
_INVALID_SKILLS = "Please pick at least one skill using the listed numbers (e.g. 1,3)."

_NO_CV_PHRASES = frozenset(
    {
        "no",
        "n",
        "no cv",
        "no resume",
        "dont have",
        "don't have",
        "dont have cv",
        "don't have cv",
        "dont have a cv",
        "don't have a cv",
        "dont have resume",
        "don't have resume",
        "without cv",
        "without resume",
        "no i dont",
        "no i don't",
        "i dont have",
        "i don't have",
        "i dont have cv",
        "i don't have cv",
        "i dont have a cv",
        "i don't have a cv",
    }
)


def is_no_cv_response(text: str) -> bool:
    """Return True when the user indicates they have no CV."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    normalized = normalized.replace("’", "'")
    if normalized in _NO_CV_PHRASES:
        return True
    return normalized.startswith("no ") and "cv" in normalized


def is_awaiting_cv_choice(stage: Optional[str]) -> bool:
    return stage in {None, STAGE_AWAITING_CV_CHOICE}


def is_manual_onboarding_stage(stage: Optional[str]) -> bool:
    return stage in MANUAL_ONBOARDING_STAGES


def _group_skills_by_category(skills: Sequence[Skill]) -> Dict[str, List[Skill]]:
    grouped: Dict[str, List[Skill]] = {}
    for skill in skills:
        category = (skill.category or "General").strip()
        grouped.setdefault(category, []).append(skill)
    return grouped


def _format_numbered_options(items: Sequence[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _parse_number_selection(text: str, max_option: int) -> List[int]:
    if max_option <= 0:
        return []
    found = re.findall(r"\d+", text)
    selected: List[int] = []
    seen = set()
    for token in found:
        value = int(token)
        if 1 <= value <= max_option and value not in seen:
            seen.add(value)
            selected.append(value)
    return selected


async def _set_stage(
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


async def start_cv_choice_prompt(db: AsyncSession, user: ChatUser) -> str:
    """Mark user as awaiting CV choice and return the intro message."""
    await _set_stage(db, user, STAGE_AWAITING_CV_CHOICE)
    return _ASK_CV_OR_NO


async def begin_manual_onboarding(db: AsyncSession, user: ChatUser) -> str:
    """Start the no-CV questionnaire."""
    await update_user_onboarding_data(db, user, {})
    await _set_stage(db, user, STAGE_MANUAL_AWAITING_NAME)
    return _ASK_NAME


async def handle_manual_onboarding_message(
    db: AsyncSession,
    user: ChatUser,
    text: str,
) -> Tuple[str, Optional[bytes], Optional[str]]:
    """Process one manual onboarding reply.

    Returns (reply_text, optional_pdf_bytes, optional_pdf_filename).
    """
    stage = user.job_search_stage
    cleaned = text.strip()

    if stage == STAGE_MANUAL_AWAITING_NAME:
        if len(cleaned) < 2:
            return _INVALID_NAME, None, None
        await update_user_display_name(db, user, cleaned)
        await _set_stage(db, user, STAGE_MANUAL_AWAITING_CATEGORY)
        all_skills = await list_skills(db)
        categories = sorted(_group_skills_by_category(all_skills))
        await update_user_onboarding_data(db, user, {"categories": categories})
        options = _format_numbered_options(categories)
        return _ASK_CATEGORY_TEMPLATE.format(name=cleaned, options=options), None, None

    if stage == STAGE_MANUAL_AWAITING_CATEGORY:
        data = get_user_onboarding_data(user)
        categories: List[str] = list(data.get("categories") or [])
        if not categories:
            all_skills = await list_skills(db)
            categories = sorted(_group_skills_by_category(all_skills))
            await update_user_onboarding_data(db, user, {"categories": categories})

        selected_indexes = _parse_number_selection(cleaned, len(categories))
        if len(selected_indexes) != 1:
            return _INVALID_CATEGORY, None, None

        category = categories[selected_indexes[0] - 1]
        all_skills = await list_skills(db)
        grouped = _group_skills_by_category(all_skills)
        category_skills = grouped.get(category, [])
        skill_names = [skill.name for skill in category_skills]

        await update_user_onboarding_data(
            db,
            user,
            {"categories": categories, "category": category, "skill_names": skill_names},
        )
        await _set_stage(db, user, STAGE_MANUAL_AWAITING_SKILLS)
        options = _format_numbered_options(skill_names)
        return (
            _ASK_SKILLS_TEMPLATE.format(category=category, options=options),
            None,
            None,
        )

    if stage == STAGE_MANUAL_AWAITING_SKILLS:
        data = get_user_onboarding_data(user)
        category = str(data.get("category") or "Professional")
        skill_names: List[str] = list(data.get("skill_names") or [])
        selected_indexes = _parse_number_selection(cleaned, len(skill_names))
        if not selected_indexes:
            return _INVALID_SKILLS, None, None

        chosen_skills = [skill_names[index - 1] for index in selected_indexes]
        full_name = (user.display_name or "Candidate").strip()
        cv_content = await generate_manual_cv_content(full_name, category, chosen_skills)
        pdf_bytes = generate_cv_pdf(
            full_name,
            chosen_skills,
            category,
            content=cv_content,
        )
        await save_user_resume_pdf(db, user, pdf_bytes)
        matched_skills = await set_user_skills_by_names(db, user, chosen_skills)
        await update_user_onboarding_data(db, user, None)
        await _set_stage(db, user, OPPORTUNITY_STAGE_AWAITING_TYPE)

        skills_text = ", ".join(skill.name for skill in matched_skills) or "none"
        reply = (
            f"Thanks! I created a CV for you based on your answers.\n\n"
            f"Your skills: {skills_text}.\n\n"
            "What are you looking for — education opportunities or job opportunities? "
            "Reply with *education* or *jobs*."
        )
        safe_name = re.sub(r"[^\w\- ]+", "", full_name).strip().replace(" ", "_") or "profile"
        filename = f"{safe_name}_CV.pdf"
        return reply, pdf_bytes, filename

    return _REMIND_CV_OR_NO, None, None
