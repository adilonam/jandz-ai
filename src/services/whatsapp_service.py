"""WhatsApp webhook parsing and send-message helpers."""

from dataclasses import dataclass
from typing import Any, List

import httpx

from src.config import settings


@dataclass
class IncomingWhatsAppMessage:
    phone_number_id: str
    from_wa_id: str
    text: str


def extract_incoming_user_messages(payload: Any) -> List[IncomingWhatsAppMessage]:
    """Extract inbound text messages from WhatsApp webhook payload."""
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
                text = str((msg.get("text") or {}).get("body") or "").strip()
                if sender and text:
                    out.append(
                        IncomingWhatsAppMessage(
                            phone_number_id=str(phone_number_id),
                            from_wa_id=sender,
                            text=text,
                        )
                    )
    return out


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
