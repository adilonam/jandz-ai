"""WhatsApp webhook parsing and send-message helpers."""

from dataclasses import dataclass
from typing import Any, List, Optional

import httpx

from src.config import settings


@dataclass
class IncomingWhatsAppMessage:
    phone_number_id: str
    from_wa_id: str
    text: Optional[str] = None
    document_id: Optional[str] = None
    document_mime_type: Optional[str] = None


def extract_incoming_user_messages(payload: Any) -> List[IncomingWhatsAppMessage]:
    """Extract inbound text and document messages from WhatsApp webhook payload."""
    out: List[IncomingWhatsAppMessage] = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return out

    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if not value.get("messages"):
                continue

            metadata = value.get("metadata") or {}
            phone_number_id = metadata.get("phone_number_id")
            if not phone_number_id:
                continue

            for msg in value.get("messages") or []:
                sender = str(msg.get("from") or "").strip()
                if not sender:
                    continue

                text = str((msg.get("text") or {}).get("body") or "").strip()
                document = msg.get("document") or {}
                document_id = str(document.get("id") or "").strip()
                document_mime_type = str(document.get("mime_type") or "").strip()

                if text or document_id:
                    out.append(
                        IncomingWhatsAppMessage(
                            phone_number_id=str(phone_number_id),
                            from_wa_id=sender,
                            text=text or None,
                            document_id=document_id or None,
                            document_mime_type=document_mime_type or None,
                        )
                    )
    return out


async def download_whatsapp_media(media_id: str) -> Optional[bytes]:
    """Download media bytes from WhatsApp Cloud API by media id."""
    if not settings.WHATSAPP_ACCESS_TOKEN:
        print("WHATSAPP_ACCESS_TOKEN is not set; cannot download media")
        return None

    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    metadata_url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_API_VERSION}/{media_id}"

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            metadata_resp = await client.get(metadata_url, headers=headers)
            metadata_resp.raise_for_status()
            metadata = metadata_resp.json()
            download_url = str(metadata.get("url") or "").strip()
            if not download_url:
                print(f"WhatsApp media metadata missing URL for media_id={media_id}")
                return None

            media_resp = await client.get(download_url, headers=headers)
            media_resp.raise_for_status()
            return media_resp.content
    except Exception as exc:
        print(f"Failed to download WhatsApp media {media_id}: {exc}")
        return None


async def send_whatsapp_text(phone_number_id: str, to_wa_id: str, body: str) -> None:
    """Send a text message through WhatsApp Cloud API."""
    
    if not settings.WHATSAPP_ACCESS_TOKEN:
        print("WHATSAPP_ACCESS_TOKEN is not set; skipping outbound reply")
        return
    url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": body},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            print(f"WhatsApp API error {response.status_code}: {response.text}")
