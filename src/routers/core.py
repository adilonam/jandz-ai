"""Public health, landing, and legacy-path redirect routes."""

from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from src.config import settings
from src.schemas import EchoRequest

router = APIRouter(tags=["core"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

# Shared with admin auth cookie name (src.routers.admin).
_ADMIN_COOKIE_NAME = "jandz_admin_auth"


@router.get("/")
async def landing_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="core/landing.html",
        context={
            "bot_name": settings.APP_NAME,
            "bot_username": settings.TELEGRAM_BOT_USERNAME,
            "telegram_url": settings.telegram_bot_url,
        },
    )


@router.get("/bot")
async def bot_landing_redirect() -> RedirectResponse:
    return RedirectResponse("/", status_code=301)


@router.get("/users")
async def legacy_users_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/users", status_code=301)


@router.get("/skills")
async def legacy_skills_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/skills", status_code=301)


@router.get("/conversations")
async def legacy_conversations_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/conversations", status_code=301)


@router.get("/conversations/{user_id}")
async def legacy_conversation_detail_redirect(user_id: int) -> RedirectResponse:
    return RedirectResponse(f"/admin/conversations/{user_id}", status_code=301)


@router.get("/coresignal")
@router.get("/mcp/coresignal")
async def legacy_coresignal_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/coresignal", status_code=301)


@router.get("/mcp/search-history")
async def legacy_search_history_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/mcp/search-history", status_code=301)


@router.post("/login")
async def legacy_login_redirect() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=303)


@router.post("/logout")
async def legacy_logout_redirect() -> RedirectResponse:
    response = RedirectResponse("/admin", status_code=303)
    response.delete_cookie(_ADMIN_COOKIE_NAME)
    return response


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.post("/echo")
async def echo(body: EchoRequest) -> Dict[str, str]:
    return {"echo": body.text}
