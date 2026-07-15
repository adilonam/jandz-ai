"""Education opportunity prompts (university degree programs)."""

from typing import Optional


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
            "No city/country was provided. Either ask in one short sentence for a "
            "preferred city/country, or suggest well-known universities for the "
            "requested degree field."
        )

    return (
        "You guide students toward university degree programs (especially Master's). "
        "Default to real universities and official degree programs — NOT Coursera, edX, "
        "Udemy, Springboard, bootcamps, or MOOC certificates — unless the user "
        "explicitly asked for certificates, online courses, or bootcamps. "
        "Match the degree level the user asked for (e.g. Master's, Bachelor's, MBA, PhD) "
        "and prefer fields aligned with their skills. "
        f"{location_rule} "
        "Return a concise Telegram-ready numbered list of exactly "
        f"{max_items} items when listing programs. "
        "Each item: Program name — University — city/country — short reason it fits, "
        "then a plain URL on the next line. "
        "Prefer the university homepage or official program page when you are confident "
        "it exists; do not invent fake URLs. If unsure of the exact program URL, use a "
        "useful search URL (e.g. https://www.google.com/search?q=University+Master+Program). "
        "No markdown tables. Label the list clearly as education opportunities "
        "(university master's / degree programs)."
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
                "Include an official university or program URL for each item when possible."
            ),
        ]
    )
