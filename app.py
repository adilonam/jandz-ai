"""Minimal FastAPI application."""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from fastapi import BackgroundTasks, FastAPI, Request, Response, status
from fastapi.responses import PlainTextResponse

load_dotenv()

# Must match Meta → WhatsApp → Configuration → Webhook → Verify token (same string in both places).
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_GRAPH_API_VERSION = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v21.0").strip() or "v21.0"

WHATSAPP_REPLY_TEXT = "hi im on testing now"

app = FastAPI(
    title="hire-chat API",
    version="0.1.0",
    description="Basic FastAPI starter.",
)


@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "hire-chat API"}


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


class EchoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=512)


@app.post("/echo")
async def echo(body: EchoRequest) -> Dict[str, str]:
    return {"echo": body.text}


def _query(request: Request, dotted: str, underscored: str) -> Optional[str]:
    """Meta sends hub.mode / hub.challenge / hub.verify_token; some clients duplicate as hub_mode."""
    q = request.query_params
    return q.get(dotted) or q.get(underscored)


@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request) -> Response:
    """Meta calls this when you save the webhook URL; must return hub.challenge as plain text if token matches."""
    mode = _query(request, "hub.mode", "hub_mode")
    token = _query(request, "hub.verify_token", "hub_verify_token")
    challenge = _query(request, "hub.challenge", "hub_challenge")

    if mode == "subscribe" and challenge:
        if WHATSAPP_VERIFY_TOKEN and token == WHATSAPP_VERIFY_TOKEN:
            return PlainTextResponse(content=challenge)
    return Response(status_code=status.HTTP_403_FORBIDDEN)


def _extract_incoming_user_messages(payload: Any) -> List[Tuple[str, str]]:
    """Return (phone_number_id, from_wa_id) for each inbound user message."""
    out: List[Tuple[str, str]] = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return out
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if not value.get("messages"):
                continue
            meta = value.get("metadata") or {}
            phone_number_id = meta.get("phone_number_id")
            if not phone_number_id:
                continue
            for msg in value.get("messages") or []:
                sender = msg.get("from")
                if sender:
                    out.append((str(phone_number_id), str(sender)))
    return out


async def _send_whatsapp_text(phone_number_id: str, to_wa_id: str, body: str) -> None:
    if not WHATSAPP_ACCESS_TOKEN:
        print("WHATSAPP_ACCESS_TOKEN is not set; skipping outbound reply")
        return
    url = f"https://graph.facebook.com/{WHATSAPP_GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": body},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=data, headers=headers)
        if r.status_code >= 400:
            print(f"WhatsApp API error {r.status_code}: {r.text}")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, str]:
    raw = await request.body()

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        print(raw.decode("utf-8", errors="replace"))
        return {"message": "ignored"}

    if isinstance(payload, dict):
        print(payload)

    for phone_number_id, from_id in _extract_incoming_user_messages(payload):
        background_tasks.add_task(
            _send_whatsapp_text,
            phone_number_id,
            from_id,
            WHATSAPP_REPLY_TEXT,
        )

    return {"message": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
