"""Shared opportunity-guidance helpers used by messaging channels."""

import re
from typing import List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.models.chat_user import ChatUser
from src.services.openai_service import generate_opportunities
from src.services.opportunity_service import (
    create_opportunities_from_payloads,
    format_telegram_opportunity_list,
)

OPPORTUNITY_STAGE_AWAITING_TYPE = "awaiting_opportunity_type"
# Legacy stages from the previous remote/onsite/location flow.
_LEGACY_AWAITING_STAGES = frozenset({"awaiting_work_mode", "awaiting_location"})

OPPORTUNITY_TYPE_EDUCATION = "education"
OPPORTUNITY_TYPE_JOBS = "jobs"

OPPORTUNITY_ASSISTANT_CTA = (
    " I can guide you toward education or job opportunities matched to your skills. "
    "Reply with education or jobs to see suggestions."
)

_EDUCATION_KEYWORDS = frozenset(
    {
        "education",
        "edu",
        "study",
        "studies",
        "studying",
        "course",
        "courses",
        "school",
        "university",
        "college",
        "degree",
        "degrees",
        "learn",
        "learning",
        "training",
        "program",
        "programme",
        "scholarship",
        "scholarships",
        "master",
        "masters",
        "master's",
        "mba",
        "phd",
        "bachelor",
        "bachelors",
        "bachelor's",
        "undergraduate",
        "graduate",
        "postgraduate",
        "diploma",
        "certification",
        "certifications",
        "bootcamp",
        "bootcamps",
    }
)
# Clear employment intent.
_STRONG_JOB_KEYWORDS = frozenset(
    {
        "job",
        "jobs",
        "career",
        "careers",
        "employment",
        "hire",
        "hiring",
        "position",
        "positions",
        "role",
        "roles",
        "vacancy",
        "vacancies",
        "opening",
        "openings",
    }
)
# Vague alone (e.g. "new work" for New York); ignored when education signals exist.
_WEAK_JOB_KEYWORDS = frozenset({"work", "working"})

_EDUCATION_PHRASES = (
    r"\bmasters?\b",
    r"\bmaster'?s\b",
    r"\bbachelors?\b",
    r"\bbachelor'?s\b",
    r"\bphd\b",
    r"\bmba\b",
    r"\bdegree\b",
    r"\buniversity\b",
    r"\bcollege\b",
    r"\bscholarship\b",
)

# Longest aliases first for substring matching (covers typos like "i new york").
_LOCATION_ALIASES = (
    ("united states", "United States"),
    ("new york city", "New York"),
    ("new york", "New York"),
    ("los angeles", "Los Angeles"),
    ("san francisco", "San Francisco"),
    ("united kingdom", "United Kingdom"),
    ("nyc", "New York"),
    ("usa", "USA"),
    ("u.s.a", "USA"),
    ("u.s.", "USA"),
    ("uk", "United Kingdom"),
    ("london", "London"),
    ("paris", "Paris"),
    ("berlin", "Berlin"),
    ("boston", "Boston"),
    ("chicago", "Chicago"),
    ("toronto", "Toronto"),
    ("montreal", "Montreal"),
    ("vancouver", "Vancouver"),
    ("casablanca", "Casablanca"),
    ("rabat", "Rabat"),
    ("madrid", "Madrid"),
    ("barcelona", "Barcelona"),
    ("amsterdam", "Amsterdam"),
    ("dubai", "Dubai"),
)


def _message_tokens(text: str) -> Set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z\-']*", text)}


def _has_education_signal(text: str, tokens: Set[str]) -> bool:
    if tokens & _EDUCATION_KEYWORDS:
        return True
    normalized = text.strip().lower()
    return any(re.search(pattern, normalized) for pattern in _EDUCATION_PHRASES)


def extract_location_hint(text: str) -> Optional[str]:
    """Best-effort city/country from free text for opportunity prompts."""
    if not text or not text.strip():
        return None

    normalized = " ".join(text.strip().lower().split())
    for alias, label in _LOCATION_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            return label

    match = re.search(
        r"\b(?:in|at|near|from)\s+([A-Za-z][A-Za-z\s\-']{1,40})",
        normalized,
    )
    if match:
        candidate = match.group(1).strip(" .,!?:;")
        # Drop trailing fillers that are not place names.
        stop = {
            "please",
            "thanks",
            "master",
            "masters",
            "education",
            "job",
            "jobs",
            "university",
            "program",
            "programme",
            "degree",
        }
        parts = [
            part
            for part in re.findall(r"[A-Za-z][A-Za-z\-']*", candidate)
            if part.lower() not in stop
        ]
        if parts:
            return " ".join(parts).title()
    return None


def normalize_opportunity_type(text: str) -> Optional[str]:
    """Return ``education`` or ``jobs`` when the user clearly chooses one.

    Education terms (master's, degree, study, …) outrank weak job words like
    ``work``, which often appear from typos (e.g. New York → "new work").
    """
    tokens = _message_tokens(text)
    if not tokens:
        return None

    wants_education = _has_education_signal(text, tokens)
    wants_strong_jobs = bool(tokens & _STRONG_JOB_KEYWORDS)
    wants_weak_jobs = bool(tokens & _WEAK_JOB_KEYWORDS)

    if wants_education and not wants_strong_jobs:
        return OPPORTUNITY_TYPE_EDUCATION
    if wants_strong_jobs and not wants_education:
        return OPPORTUNITY_TYPE_JOBS
    if wants_education and wants_strong_jobs:
        # Master's / study queries win over co-occurring job wording.
        return OPPORTUNITY_TYPE_EDUCATION
    if wants_weak_jobs:
        return OPPORTUNITY_TYPE_JOBS
    return None


def is_opportunity_request(text: str) -> bool:
    """True when the user asks about education or job opportunities."""
    return normalize_opportunity_type(text) is not None or bool(
        _message_tokens(text)
        & (
            _EDUCATION_KEYWORDS
            | _STRONG_JOB_KEYWORDS
            | _WEAK_JOB_KEYWORDS
            | {"opportunity", "opportunities"}
        )
    )


def is_awaiting_opportunity_choice(stage: Optional[str]) -> bool:
    if not stage:
        return False
    return stage == OPPORTUNITY_STAGE_AWAITING_TYPE or stage in _LEGACY_AWAITING_STAGES


def append_opportunity_cta(reply_text: str) -> str:
    if OPPORTUNITY_ASSISTANT_CTA.lower() in reply_text.lower():
        return reply_text
    return f"{reply_text.rstrip()}{OPPORTUNITY_ASSISTANT_CTA}"


async def opportunities_reply_for_user(
    db: AsyncSession,
    user_id: int,
    opportunity_type: str,
    request_text: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Generate education or job opportunity suggestions from the user's stored skills."""
    user = await db.scalar(
        select(ChatUser)
        .options(selectinload(ChatUser.skills))
        .where(ChatUser.id == user_id)
    )
    if not user:
        return "I could not find your profile. Please send your CV PDF again."

    skill_names: List[str] = [skill.name for skill in user.skills]
    location = extract_location_hint(request_text or "")
    result = await generate_opportunities(
        opportunity_type=opportunity_type,
        skill_names=skill_names,
        request_text=request_text,
        location=location,
    )

    if not result.opportunities:
        return result.fallback_text or (
            "I could not list opportunities right now. Please try again."
        )

    try:
        rows = await create_opportunities_from_payloads(
            db,
            result.opportunities,
            opportunity_type=opportunity_type,
            chat_user_id=user.id,
            skills=skill_names,
            default_location=location,
        )
    except Exception as exc:
        print(f"Failed to persist opportunities: {exc}")
        return (
            result.fallback_text
            or "I found some opportunities but could not save them. Please try again."
        )

    if not rows:
        return (
            result.fallback_text
            or "I could not list opportunities right now. Please try again."
        )

    public_base = (base_url or settings.public_base_url or "").rstrip("/")
    if public_base:
        return format_telegram_opportunity_list(
            rows,
            base_url=public_base,
            opportunity_type=opportunity_type,
        )

    # No PUBLIC_BASE_URL configured — still return local paths so links are identifiable.
    lines = ["Here are some opportunities matched to your profile:", ""]
    for index, opportunity in enumerate(rows, start=1):
        title = (opportunity.title or f"Opportunity {index}").strip()
        lines.append(f"{index}. {title}")
        lines.append(f"/opportunities/{opportunity.id}")
        lines.append("")
    return "\n".join(lines).rstrip()

