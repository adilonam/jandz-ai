"""Public opportunity detail pages."""

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.services.opportunity_service import get_opportunity_by_id

router = APIRouter(tags=["opportunities"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def _source_label(url: Optional[str]) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    host = parsed.netloc or ""
    if host.startswith("www."):
        host = host[4:]
    return host or url.strip()


@router.get("/opportunities/{opportunity_id}")
async def opportunity_detail(
    opportunity_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    opportunity = await get_opportunity_by_id(db, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    tips = opportunity.tips_as_list()
    funding_label = "FUNDING" if opportunity.type == "education" else "SALARY"
    display_name = ""
    if opportunity.chat_user and opportunity.chat_user.display_name:
        display_name = opportunity.chat_user.display_name

    return templates.TemplateResponse(
        request=request,
        name="opportunities/detail.html",
        context={
            "opportunity": opportunity,
            "tips": tips,
            "funding_label": funding_label,
            "source_label": _source_label(opportunity.source_url),
            "display_name": display_name,
        },
    )
