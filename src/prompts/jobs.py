"""Job opportunity prompts."""

from typing import Optional


def build_jobs_system_prompt(*, max_items: int) -> str:
    """System instructions for listing job opportunities."""
    return (
        "You guide people seeking work toward job opportunities. "
        "Suggest realistic roles and example openings matched to their skills "
        "(title, typical employer type or company example, and a short fit reason). "
        "Return a concise Telegram-ready numbered list of exactly "
        f"{max_items} items. "
        "Each item on its own block: title — company/type — short fit reason, "
        "then a plain URL on the next line. "
        "Prefer a real careers/job page only when you are confident it exists; "
        "do not invent fake or broken URLs. If unsure, use a useful search URL "
        "(for example LinkedIn or Google job search). "
        "No markdown tables or link titles. Label the list clearly as job opportunities."
    )


def build_jobs_user_prompt(
    *,
    skills_label: str,
    user_request: Optional[str] = None,
    location: Optional[str] = None,
    max_items: int,
) -> str:
    """User message for listing job opportunities."""
    request = (user_request or "").strip() or "(none — user chose jobs)"
    location_label = (location or "").strip()
    location_line = (
        f"Preferred location: {location_label}"
        if location_label
        else "Preferred location: (not specified)"
    )
    return (
        f"Skills: {skills_label}\n"
        f"User request: {request}\n"
        f"{location_line}\n"
        f"Suggest {max_items} job opportunities tailored to these skills. "
        "Include a URL for each item."
    )
