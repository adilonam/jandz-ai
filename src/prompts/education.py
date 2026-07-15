"""Education opportunity prompts (university degree programs)."""

from typing import Optional


def _json_shape_instructions(max_items: int) -> str:
    return (
        f"Return STRICT JSON only (no markdown fences, no prose outside JSON) with exactly "
        f"{max_items} items in this shape:\n"
        "{\n"
        '  "opportunities": [\n'
        "    {\n"
        '      "title": "Program or scholarship name",\n'
        '      "organization": "University or provider",\n'
        '      "category": "optional tag e.g. STUDY ABROAD",\n'
        '      "location": "city/country",\n'
        '      "description": "1-3 sentences",\n'
        '      "deadline": "optional date or text",\n'
        '      "funding_or_salary": "optional funding summary",\n'
        '      "eligibility": "optional eligibility summary",\n'
        '      "contact_name": "optional",\n'
        '      "contact_email": "optional",\n'
        '      "contact_phone": "optional",\n'
        '      "source_url": "official site when confident",\n'
        '      "apply_url": "apply or program URL when confident",\n'
        '      "tips": ["optional tip 1", "optional tip 2"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Omit unknown optional fields or use null. Do not invent broken URLs; "
        "if unsure of apply_url, use a useful search URL."
    )


def build_education_system_prompt(
    *,
    max_items: int,
    location: Optional[str] = None,
) -> str:
    """System instructions for listing university education opportunities."""
    location_label = (location or "").strip()
    if location_label:
        location_rule = (
            f"Location constraint: ONLY suggest universities/colleges located in "
            f"{location_label} (city and/or that country). Do not suggest programs "
            f"outside this location."
        )
    else:
        location_rule = (
            "No city/country was provided. Prefer well-known universities for the "
            "requested degree field; leave location accurate when known."
        )

    return (
        "You guide students toward university degree programs (especially Master's). "
        "Default to real universities and official degree programs — NOT Coursera, edX, "
        "Udemy, Springboard, bootcamps, or MOOC certificates — unless the user "
        "explicitly asked for certificates, online courses, or bootcamps. "
        "Match the degree level the user asked for (e.g. Master's, Bachelor's, MBA, PhD) "
        "and prefer fields aligned with their skills. "
        f"{location_rule} "
        + _json_shape_instructions(max_items)
    )


def build_education_user_prompt(
    *,
    skills_label: str,
    user_request: Optional[str] = None,
    location: Optional[str] = None,
    max_items: int,
) -> str:
    """User message for listing university education opportunities."""
    request = (user_request or "").strip() or "(none — user chose education)"
    location_label = (location or "").strip() or "(not found)"
    return "\n".join(
        [
            f"Skills: {skills_label}",
            f"User request: {request}",
            f"Parsed location: {location_label}",
            (
                f"Suggest {max_items} university degree programs tailored to this request. "
                "Fill optional fields when you know them. Return JSON only."
            ),
        ]
    )
