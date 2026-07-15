"""Select opportunity prompt builders from Telegram education vs jobs choice."""

from dataclasses import dataclass
from typing import Optional

from src.prompts.education import (
    build_education_system_prompt,
    build_education_user_prompt,
)
from src.prompts.jobs import build_jobs_system_prompt, build_jobs_user_prompt

OPPORTUNITY_TYPE_EDUCATION = "education"
OPPORTUNITY_TYPE_JOBS = "jobs"


@dataclass(frozen=True)
class PromptPair:
    """System + user messages for a single chat completion call."""

    system: str
    user: str


def build_opportunity_prompts(
    opportunity_type: str,
    *,
    skills_label: str,
    max_items: int,
    user_request: Optional[str] = None,
    location: Optional[str] = None,
) -> PromptPair:
    """Map ``education`` / ``jobs`` to the matching prompt module builders."""
    normalized = (opportunity_type or "").strip().lower()
    if normalized == OPPORTUNITY_TYPE_EDUCATION:
        return PromptPair(
            system=build_education_system_prompt(
                max_items=max_items,
                location=location,
            ),
            user=build_education_user_prompt(
                skills_label=skills_label,
                user_request=user_request,
                location=location,
                max_items=max_items,
            ),
        )

    return PromptPair(
        system=build_jobs_system_prompt(max_items=max_items),
        user=build_jobs_user_prompt(
            skills_label=skills_label,
            user_request=user_request,
            location=location,
            max_items=max_items,
        ),
    )
