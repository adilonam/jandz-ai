"""MCP integration services."""

from typing import Any, Dict

import httpx

from src.config import settings

CORESIGNAL_MCP_URL = "https://mcp.coresignal.com/mcp"


async def run_coresignal_jobs_prompt(prompt: str) -> Dict[str, Any]:
    """Send a prompt to CoreSignal MCP through OpenAI Responses and return raw JSON."""
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing.")
    if not settings.CORESIGNAL_API_KEY:
        raise ValueError("CORESIGNAL_API_KEY is missing.")

    payload = {
        "model": settings.OPENAI_MODEL,
        "input": prompt,
        "tools": [
            {
                "type": "mcp",
                "server_label": "coresignal",
                "server_url": CORESIGNAL_MCP_URL,
                "headers": {"apikey": settings.CORESIGNAL_API_KEY},
                "require_approval": "never",
            }
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=75.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        details = exc.response.text[:500]
        raise RuntimeError(f"OpenAI returned HTTP {exc.response.status_code}: {details}") from exc
    except Exception as exc:
        raise RuntimeError(f"CoreSignal MCP request failed: {exc}") from exc
