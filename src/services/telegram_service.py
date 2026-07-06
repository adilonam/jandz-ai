"""Telegram webhook parsing and send-message helpers."""

from dataclasses import dataclass
from typing import Any, List, Optional

import httpx

from src.config import settings


@dataclass
class IncomingTelegramMessage:
    chat_id: int
    text: Optional[str] = None
    document_file_id: Optional[str] = None
    document_mime_type: Optional[str] = None
    voice_file_id: Optional[str] = None


def _telegram_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


def extract_incoming_user_messages(payload: Any) -> List[IncomingTelegramMessage]:
    """Extract inbound text and document messages from a Telegram webhook update."""
    out: List[IncomingTelegramMessage] = []
    if not isinstance(payload, dict):
        return out

    message = payload.get("message") or payload.get("edited_message")
    if not isinstance(message, dict):
        return out

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return out

    text = str(message.get("text") or message.get("caption") or "").strip()
    document = message.get("document") or {}
    document_file_id = str(document.get("file_id") or "").strip()
    document_mime_type = str(document.get("mime_type") or "").strip()
    voice = message.get("voice") or {}
    voice_file_id = str(voice.get("file_id") or "").strip()

    if text or document_file_id or voice_file_id:
        out.append(
            IncomingTelegramMessage(
                chat_id=int(chat_id),
                text=text or None,
                document_file_id=document_file_id or None,
                document_mime_type=document_mime_type or None,
                voice_file_id=voice_file_id or None,
            )
        )
    return out


async def download_telegram_file(file_id: str) -> Optional[bytes]:
    """Download file bytes from Telegram by file id."""
    if not settings.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set; cannot download media")
        return None

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            file_resp = await client.get(_telegram_api_url("getFile"), params={"file_id": file_id})
            file_resp.raise_for_status()
            file_path = str((file_resp.json().get("result") or {}).get("file_path") or "").strip()
            if not file_path:
                print(f"Telegram getFile missing file_path for file_id={file_id}")
                return None

            download_url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
            media_resp = await client.get(download_url)
            media_resp.raise_for_status()
            return media_resp.content
    except Exception as exc:
        print(f"Failed to download Telegram file {file_id}: {exc}")
        return None


async def send_telegram_text(chat_id: int, body: str) -> None:
    """Send a text message through the Telegram Bot API."""
    if not settings.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set; skipping outbound reply")
        return

    payload = {
        "chat_id": chat_id,
        "text": body,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(_telegram_api_url("sendMessage"), json=payload)
        if response.status_code >= 400:
            print(f"Telegram API error {response.status_code}: {response.text}")
