"""Basic health and utility routes."""

import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_db
from src.schemas import EchoRequest, McpPromptRequest
from src.services.conversation_service import (
    list_conversation_user_summaries,
    list_messages_for_user,
)
from src.services.job_search_history_service import (
    count_job_search_history,
    create_job_search_history,
    list_job_search_history,
)
from src.services.mcp_chat_service import run_coresignal_jobs_prompt
from src.services.skill_service import list_skills
from src.services.user_service import (
    delete_whatsapp_user_by_id,
    get_whatsapp_user_by_id,
    list_whatsapp_users,
)

router = APIRouter(tags=["core"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

ADMIN_COOKIE_NAME = "jandz_admin_auth"


def _is_auth_configured() -> bool:
    return bool(settings.ADMIN_LOGIN and settings.ADMIN_PASSWORD and settings.ADMIN_SESSION_SECRET)


def _expected_auth_token() -> str:
    payload = f"{settings.ADMIN_LOGIN}:{settings.ADMIN_PASSWORD}".encode("utf-8")
    secret = settings.ADMIN_SESSION_SECRET.encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _is_authenticated(request: Request) -> bool:
    if not _is_auth_configured():
        return False
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    return bool(token) and hmac.compare_digest(token, _expected_auth_token())


def _format_datetime(dt: datetime) -> str:
    """Format timestamps for compact dashboard display."""
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _require_auth(request: Request) -> None:
    if not _is_authenticated(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.get("/")
async def root(request: Request, db: AsyncSession = Depends(get_db)):
    if not _is_auth_configured():
        return templates.TemplateResponse(
            request=request,
            name="core/login.html",
            context={
                "error": "Missing ADMIN_LOGIN, ADMIN_PASSWORD, or ADMIN_SESSION_SECRET in environment."
            },
        )
    if not _is_authenticated(request):
        error = ""
        if request.query_params.get("error") == "invalid_credentials":
            error = "Invalid login or password."
        return templates.TemplateResponse(
            request=request,
            name="core/login.html",
            context={"error": error},
        )

    users = await list_whatsapp_users(db)
    skills = await list_skills(db)
    mcp_search_history_count = await count_job_search_history(db)
    users_with_resume = sum(1 for user in users if user.resume_pdf)
    return templates.TemplateResponse(
        request=request,
        name="core/dashboard.html",
        context={
            "users_count": len(users),
            "skills_count": len(skills),
            "mcp_search_history_count": mcp_search_history_count,
            "users_with_resume_count": users_with_resume,
        },
    )


@router.get("/users")
async def users_page(request: Request, db: AsyncSession = Depends(get_db)):
    _require_auth(request)

    users = await list_whatsapp_users(db)
    user_rows = [
        {
            "id": user.id,
            "phone_number": user.phone_number,
            "display_name": user.display_name or "-",
            "created_at": _format_datetime(user.created_at),
            "has_resume": bool(user.resume_pdf),
            "skills": [skill.name for skill in user.skills],
        }
        for user in users
    ]
    return templates.TemplateResponse(
        request=request,
        name="core/users.html",
        context={"users": user_rows},
    )


@router.get("/skills")
async def skills_page(request: Request, db: AsyncSession = Depends(get_db)):
    _require_auth(request)

    skills = await list_skills(db)
    skill_rows = [
        {
            "id": skill.id,
            "category": skill.category,
            "name": skill.name,
            "users_count": len(skill.users),
            "users": [
                {
                    "id": user.id,
                    "phone_number": user.phone_number,
                    "display_name": user.display_name or "-",
                }
                for user in skill.users
            ],
        }
        for skill in skills
    ]
    return templates.TemplateResponse(
        request=request,
        name="core/skills.html",
        context={"skills": skill_rows},
    )


@router.get("/conversations")
async def conversations_page(request: Request, db: AsyncSession = Depends(get_db)):
    _require_auth(request)

    conversations = await list_conversation_user_summaries(db)
    conversation_rows = [
        {
            "user_id": row["user_id"],
            "phone_number": row["phone_number"],
            "display_name": row["display_name"],
            "messages_count": row["messages_count"],
            "last_message_at": _format_datetime(row["last_message_at"]),
        }
        for row in conversations
    ]

    return templates.TemplateResponse(
        request=request,
        name="core/conversations.html",
        context={"conversations": conversation_rows},
    )


@router.get("/conversations/{user_id}")
async def conversation_detail_page(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_auth(request)

    user = await get_whatsapp_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    messages = await list_messages_for_user(db, user_id=user_id)
    message_rows = [
        {
            "direction": message.direction,
            "text": message.text,
            "created_at": _format_datetime(message.created_at),
        }
        for message in messages
    ]

    return templates.TemplateResponse(
        request=request,
        name="core/conversation_detail.html",
        context={
            "phone_number": user.phone_number,
            "display_name": user.display_name or "-",
            "messages": message_rows,
        },
    )


@router.get("/mcp/coresignal")
async def mcp_coresignal_test_page(request: Request):
    _require_auth(request)
    return templates.TemplateResponse(
        request=request,
        name="core/mcp_coresignal_test.html",
        context={},
    )


@router.get("/mcp/search-history")
async def mcp_search_history_page(request: Request, db: AsyncSession = Depends(get_db)):
    _require_auth(request)
    rows = await list_job_search_history(db, limit=200)
    history_rows = [
        {
            "id": row.id,
            "provider": row.provider,
            "prompt_query": row.prompt_query,
            "response_payload": row.response_payload,
            "created_at": _format_datetime(row.created_at),
        }
        for row in rows
    ]
    return templates.TemplateResponse(
        request=request,
        name="core/mcp_search_history.html",
        context={"history_rows": history_rows},
    )


@router.post("/api/mcp/coresignal/jobs")
async def mcp_coresignal_jobs_api(
    request: Request,
    body: McpPromptRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    _require_auth(request)
    try:
        payload = await run_coresignal_jobs_prompt(body.prompt)
        await create_job_search_history(
            db,
            prompt_query=body.prompt,
            response_payload=payload,
            provider="coresignal_mcp",
        )
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/login")
async def login(login: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    if not _is_auth_configured():
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    is_login_valid = hmac.compare_digest(login, settings.ADMIN_LOGIN)
    is_password_valid = hmac.compare_digest(password, settings.ADMIN_PASSWORD)
    if not (is_login_valid and is_password_valid):
        return RedirectResponse("/?error=invalid_credentials", status_code=status.HTTP_303_SEE_OTHER)

    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=_expected_auth_token(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 8,
    )
    return response


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response


@router.get("/admin/users/{user_id}/resume")
async def download_resume(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    _require_auth(request)

    user = await get_whatsapp_user_by_id(db, user_id)
    if not user or not user.resume_pdf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    safe_phone = user.phone_number.replace("+", "").replace(" ", "")
    filename = f"resume-{safe_phone or user.id}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=user.resume_pdf, media_type="application/pdf", headers=headers)


@router.post("/admin/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    _require_auth(request)
    await delete_whatsapp_user_by_id(db, user_id)
    return RedirectResponse("/users", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.post("/echo")
async def echo(body: EchoRequest) -> Dict[str, str]:
    return {"echo": body.text}
