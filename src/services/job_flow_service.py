"""Shared opportunity-guidance helpers used by messaging channels."""

import re
from typing import List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.models.chat_user import ChatUser
from src.services.coresignal_service import (
    coresignal_job_to_opportunity_payload,
    search_and_collect_jobs,
)
from src.services.job_search_history_service import create_job_search_history
from src.services.openai_service import extract_job_search_params, generate_opportunities
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


_REQUEST_PREFIXES = re.compile(
    r"^(?:"
    r"give me|find me|show me|get me|i want|i need|looking for|search for|"
    r"can you find|please find|help me find|i am looking for|i'm looking for"
    r")\s+",
    re.IGNORECASE,
)

_JOB_KEYWORD_PATTERN = r"(?:jobs?|positions?|roles?|openings?|vacancies?)"
_LOCATION_PREPOSITION = r"\b(?:in|at|near|from)\b"


def _clean_title_candidate(candidate: str) -> Optional[str]:
    candidate = candidate.strip(" ,")
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered in _STRONG_JOB_KEYWORDS or lowered in _WEAK_JOB_KEYWORDS:
        return None
    if _has_education_signal(candidate, _message_tokens(candidate)):
        return None
    return candidate


def extract_job_title_hint(text: str) -> Optional[str]:
    """Best-effort role/title from free text (e.g. ``truck driver jobs in Hungary``)."""
    if not text or not text.strip():
        return None

    normalized = " ".join(text.strip().split())
    normalized = _REQUEST_PREFIXES.sub("", normalized).strip()
    if not normalized:
        return None

    # "jobs for truck driver in Germany"
    match = re.search(
        rf"\b{_JOB_KEYWORD_PATTERN}\s+for\s+"
        rf"(.+?)(?:\s+{_LOCATION_PREPOSITION}\b|$)",
        normalized,
        re.IGNORECASE,
    )
    if match:
        title = _clean_title_candidate(match.group(1))
        if title:
            print(f"[job_title_extract] matched jobs-for pattern title={title!r} from={text!r}")
            return title

    # "truck driver jobs in Hungary"
    match = re.search(
        rf"^(.+?)\s+{_JOB_KEYWORD_PATTERN}\b",
        normalized,
        re.IGNORECASE,
    )
    if match:
        title = _clean_title_candidate(match.group(1))
        if title:
            print(f"[job_title_extract] matched title-jobs pattern title={title!r} from={text!r}")
            return title

    # "software engineer in Berlin" (no job keyword)
    match = re.search(
        rf"^(.+?)\s+{_LOCATION_PREPOSITION}\s+[A-Za-z]",
        normalized,
        re.IGNORECASE,
    )
    if match:
        title = _clean_title_candidate(match.group(1))
        if title:
            print(f"[job_title_extract] matched title-in-location pattern title={title!r} from={text!r}")
            return title

    print(f"[job_title_extract] no title extracted from={text!r}")
    return None


def extract_work_mode_hint(text: str) -> str:
    """Return ``remote``, ``onsite``, or empty string from user text."""
    normalized = (text or "").strip().lower()
    if not normalized:
        return ""
    if re.search(r"\bremote\b|\bwork from home\b|\bwfh\b", normalized):
        return "remote"
    if re.search(r"\bhybrid\b", normalized):
        return "hybrid"
    if re.search(r"\bonsite\b|\bon-site\b|\bon site\b|\bin[- ]office\b", normalized):
        return "onsite"
    return ""


def _job_search_title(skill_names: List[str], request_text: Optional[str]) -> str:
    title_hint = extract_job_title_hint(request_text or "")
    if title_hint:
        return title_hint
    cleaned = [name.strip() for name in skill_names if name.strip()]
    if cleaned:
        return " ".join(cleaned[:4])
    return "jobs"


async def _resolve_job_search_params(
    skill_names: List[str],
    request_text: Optional[str],
    location: Optional[str],
) -> dict:
    """Use OpenAI to extract search params, with regex fallback."""
    prompt = (request_text or "").strip()
    params = None

    if prompt:
        params = await extract_job_search_params(prompt)

    if params and (params.title or params.location or params.country):
        title = params.title or _job_search_title(skill_names, request_text)
        location_label = (
            params.location
            or params.country
            or location
            or extract_location_hint(prompt)
            or ""
        )
        work_mode = params.work_mode or extract_work_mode_hint(prompt)
        limit = params.limit or 5
    else:
        title = _job_search_title(skill_names, request_text)
        location_label = location or extract_location_hint(prompt) or ""
        work_mode = extract_work_mode_hint(prompt)
        limit = 5
        print(
            f"[job_search] regex fallback params: title={title!r} "
            f"location={location_label!r} work_mode={work_mode!r} limit={limit}"
        )

    return {
        "title": title,
        "location": location_label,
        "work_mode": work_mode,
        "limit": limit,
    }


async def _jobs_reply_via_coresignal(
    db: AsyncSession,
    user: ChatUser,
    skill_names: List[str],
    request_text: Optional[str],
    location: Optional[str],
    base_url: Optional[str],
) -> str:
    if not settings.CORESIGNAL_API_KEY:
        return (
            "Job search is not configured yet. Please set CORESIGNAL_API_KEY "
            "and try again."
        )

    resolved = await _resolve_job_search_params(skill_names, request_text, location)
    title = resolved["title"]
    location_label = resolved["location"]
    work_mode = resolved["work_mode"]
    search_limit = resolved["limit"]

    print(
        f"[job_search] CoreSignal search with extracted params user_id={user.id} "
        f"title={title!r} location={location_label!r} work_mode={work_mode!r} "
        f"limit={search_limit} skills={skill_names!r}"
    )

    try:
        result = await search_and_collect_jobs(
            title=title,
            location=location_label,
            work_mode=work_mode,
            limit=search_limit,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"CoreSignal job search failed: {exc}")
        return "I could not search job listings right now. Please try again."

    jobs = result.get("jobs") or []
    print(
        f"[job_search] CoreSignal returned {len(jobs)} jobs for user_id={user.id} "
        f"title={title!r} location={location_label!r}"
    )
    if not jobs:
        return (
            "I could not find job listings matching your profile right now. "
            "Try a different location or reply with a role (e.g. truck driver jobs in Hungary)."
        )

    payloads = [coresignal_job_to_opportunity_payload(job) for job in jobs]
    try:
        prompt_query = (
            f"title={title}; location={location_label}; "
            f"work_mode={work_mode}; limit={search_limit}; source=telegram"
        )
        await create_job_search_history(
            db,
            prompt_query=prompt_query,
            response_payload=result["history_payload"],
            provider="coresignal_api",
        )
        rows = await create_opportunities_from_payloads(
            db,
            payloads,
            opportunity_type=OPPORTUNITY_TYPE_JOBS,
            chat_user_id=user.id,
            skills=skill_names,
            default_location=location_label or None,
        )
    except Exception as exc:
        print(f"Failed to persist CoreSignal job opportunities: {exc}")
        return "I found job listings but could not save them. Please try again."

    if not rows:
        return "I could not list job opportunities right now. Please try again."

    public_base = (base_url or settings.public_base_url or "").rstrip("/")
    if public_base:
        return format_telegram_opportunity_list(
            rows,
            base_url=public_base,
            opportunity_type=OPPORTUNITY_TYPE_JOBS,
        )

    lines = ["Here are some job opportunities matched to your profile:", ""]
    for index, opportunity in enumerate(rows, start=1):
        title_line = (opportunity.title or f"Opportunity {index}").strip()
        lines.append(f"{index}. {title_line}")
        lines.append(f"/opportunities/{opportunity.id}")
        lines.append("")
    return "\n".join(lines).rstrip()


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

    print(
        f"[opportunity_search] user_id={user_id} type={opportunity_type!r} "
        f"skills={skill_names!r} location={location!r} request_text={request_text!r}"
    )

    if opportunity_type == OPPORTUNITY_TYPE_JOBS:
        return await _jobs_reply_via_coresignal(
            db,
            user,
            skill_names,
            request_text,
            location,
            base_url,
        )

    print(
        f"[education_search] starting OpenAI education search user_id={user_id} "
        f"skills={skill_names!r} location={location!r} request_text={request_text!r}"
    )
    result = await generate_opportunities(
        opportunity_type=opportunity_type,
        skill_names=skill_names,
        request_text=request_text,
        location=location,
    )

    opp_count = len(result.opportunities)
    print(
        f"[education_search] OpenAI returned {opp_count} opportunities "
        f"user_id={user_id} fallback={bool(result.fallback_text)}"
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

