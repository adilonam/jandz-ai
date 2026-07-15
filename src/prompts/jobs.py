"""Job opportunity prompts."""

from typing import Optional


def _json_shape_instructions(max_items: int) -> str:
    return (
        f"Return STRICT JSON only (no markdown fences, no prose outside JSON) with exactly "
        f"{max_items} items in this shape:\n"
        "{\n"
        '  "opportunities": [\n'
        "    {\n"
        '      "title": "Job title",\n'
        '      "organization": "Company or employer type",\n'
        '      "category": "optional tag e.g. REMOTE",\n'
        '      "location": "city/country or Remote",\n'
        '      "description": "1-3 sentences on role and fit",\n'
        '      "deadline": "optional date or text",\n'
        '      "funding_or_salary": "optional compensation summary",\n'
        '      "eligibility": "optional requirements summary",\n'
        '      "contact_name": "optional",\n'
        '      "contact_email": "optional",\n'
        '      "contact_phone": "optional",\n'
        '      "source_url": "careers site when confident (not a LinkedIn /jobs/view/ link)",\n'
        '      "apply_url": "LinkedIn jobs search URL (keywords + location)",\n'
        '      "tips": ["optional tip 1", "optional tip 2"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Omit unknown optional fields or use null. "
        "For apply_url ALWAYS use a LinkedIn jobs SEARCH URL shaped like "
        "https://www.linkedin.com/jobs/search/?keywords=ROLE+SKILLS&location=PLACE "
        "(URL-encode spaces). Build keywords from the role/title plus relevant user skills; "
        "use the preferred location (or the opportunity location). "
        "NEVER use direct LinkedIn job posting links (linkedin.com/jobs/view/...). "
        "Those postings often close; search links stay useful."
    )


def build_jobs_system_prompt(*, max_items: int) -> str:
    """System instructions for listing job opportunities."""
    return (
        "You guide people seeking work toward job opportunities. "
        "Suggest realistic roles matched to their skills "
        "(title, typical employer type or company example, and a short fit reason). "
        "Do not point applicants at specific LinkedIn job posting IDs; "
        "always give LinkedIn jobs search links instead. "
        + _json_shape_instructions(max_items)
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
        "Set each apply_url to a LinkedIn jobs search link using role keywords "
        "and the preferred location — never a linkedin.com/jobs/view/ URL. "
        "Fill optional fields when you know them. Return JSON only."
    )
