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
        '      "source_url": "official employer/career site when confident",\n'
        '      "apply_url": "official careers or apply page when confident",\n'
        '      "tips": ["optional tip 1", "optional tip 2"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Omit unknown optional fields or use null. "
        "NEVER use LinkedIn (linkedin.com) as source_url, apply_url, or listing host — "
        "no LinkedIn search links, job view links, or LinkedIn-sourced opportunities. "
        "Prefer official company career pages or employer apply URLs instead. "
        "Do not invent broken URLs; if unsure of apply_url, omit it or use null."
    )


def build_jobs_system_prompt(*, max_items: int) -> str:
    """System instructions for listing job opportunities."""
    return (
        "You guide people seeking work toward job opportunities. "
        "Suggest realistic roles matched to their skills "
        "(title, typical employer type or company example, and a short fit reason). "
        "Do not use LinkedIn as a source or apply destination; "
        "point applicants at official employer/career sites instead. "
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
        "Set each source_url and apply_url to an official employer or careers-site "
        "domain — never linkedin.com. "
        "Fill optional fields when you know them. Return JSON only."
    )
