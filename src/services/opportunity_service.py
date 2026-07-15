"""Persist and load opportunity records."""

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.opportunity import Opportunity

_OPPORTUNITY_TYPES = frozenset({"job", "education"})


def _optional_str(value: Any, *, max_len: Optional[int] = None) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        return text[:max_len]
    return text


def _normalize_tips(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, list):
        tips = [str(item).strip() for item in value if str(item).strip()]
        return tips or None
    text = str(value).strip()
    return text or None


def normalize_opportunity_payload(
    payload: Dict[str, Any],
    *,
    opportunity_type: str,
) -> Dict[str, Any]:
    """Map AI JSON fields into Opportunity column values."""
    kind = (opportunity_type or "").strip().lower()
    if kind == "jobs":
        kind = "job"
    if kind not in _OPPORTUNITY_TYPES:
        kind = "job"

    apply_url = _optional_str(payload.get("apply_url") or payload.get("url"))
    source_url = _optional_str(payload.get("source_url") or payload.get("website"))

    return {
        "type": kind,
        "title": _optional_str(payload.get("title"), max_len=512),
        "organization": _optional_str(
            payload.get("organization") or payload.get("provider"),
            max_len=512,
        ),
        "category": _optional_str(payload.get("category") or payload.get("tag"), max_len=120),
        "location": _optional_str(payload.get("location"), max_len=255),
        "description": _optional_str(payload.get("description")),
        "deadline": _optional_str(payload.get("deadline"), max_len=255),
        "funding_or_salary": _optional_str(
            payload.get("funding_or_salary")
            or payload.get("funding")
            or payload.get("salary")
            or payload.get("compensation")
        ),
        "eligibility": _optional_str(payload.get("eligibility")),
        "contact_name": _optional_str(payload.get("contact_name"), max_len=255),
        "contact_email": _optional_str(payload.get("contact_email"), max_len=255),
        "contact_phone": _optional_str(payload.get("contact_phone"), max_len=64),
        "source_url": source_url,
        "apply_url": apply_url,
        "tips": _normalize_tips(payload.get("tips")),
    }


async def create_opportunity(
    session: AsyncSession,
    data: Dict[str, Any],
    *,
    chat_user_id: Optional[int] = None,
) -> Opportunity:
    """Create and persist one opportunity row."""
    row = Opportunity(
        chat_user_id=chat_user_id,
        **data,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def create_opportunities_from_payloads(
    session: AsyncSession,
    payloads: Sequence[Dict[str, Any]],
    *,
    opportunity_type: str,
    chat_user_id: Optional[int] = None,
) -> List[Opportunity]:
    """Normalize AI payloads and insert multiple opportunity rows."""
    rows: List[Opportunity] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        data = normalize_opportunity_payload(payload, opportunity_type=opportunity_type)
        if not any(
            data.get(key)
            for key in ("title", "organization", "description", "apply_url", "source_url")
        ):
            continue
        row = Opportunity(chat_user_id=chat_user_id, **data)
        session.add(row)
        rows.append(row)

    if not rows:
        return []

    await session.commit()
    for row in rows:
        await session.refresh(row)
    return rows


async def get_opportunity_by_id(
    session: AsyncSession,
    opportunity_id: int,
) -> Optional[Opportunity]:
    """Return one opportunity by primary key."""
    return await session.scalar(
        select(Opportunity).where(Opportunity.id == opportunity_id)
    )


def format_telegram_opportunity_list(
    opportunities: Sequence[Opportunity],
    *,
    base_url: str,
    opportunity_type: str,
) -> str:
    """Build a short Telegram list linking to public detail pages."""
    kind = "education" if opportunity_type == "education" else "job"
    label = "education opportunities" if kind == "education" else "job opportunities"
    base = base_url.rstrip("/")

    lines = [f"Here are some {label} matched to your profile:", ""]
    for index, opportunity in enumerate(opportunities, start=1):
        title = (opportunity.title or opportunity.organization or f"Opportunity {index}").strip()
        org = (opportunity.organization or "").strip()
        if org and org.lower() not in title.lower():
            heading = f"{index}. {title} — {org}"
        else:
            heading = f"{index}. {title}"
        lines.append(heading)
        lines.append(f"{base}/opportunities/{opportunity.id}")
        lines.append("")

    return "\n".join(lines).rstrip()
