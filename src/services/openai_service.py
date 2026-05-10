"""OpenAI integration service."""

import httpx

from src.config import settings


async def generate_openai_reply(user_text: str) -> str:
    """Generate a WhatsApp response from OpenAI."""
    if not settings.OPENAI_API_KEY:
        return "I am not configured yet. Please set OPENAI_API_KEY."

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": settings.OPENAI_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(f"OpenAI API request failed: {exc}")
        return "Sorry, I could not generate a response right now."

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print(f"Unexpected OpenAI response: {data}")
        return "Sorry, I could not generate a response right now."

    text = str(content).strip()
    return text or "Sorry, I could not generate a response right now."
