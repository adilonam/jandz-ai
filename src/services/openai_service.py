"""OpenAI integration service."""

import json
from typing import List, Optional, Sequence

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


async def extract_skills_from_resume(
    resume_text: str,
    available_skills: Sequence[str],
) -> List[str]:
    """Use AI to pick matching canonical skills for a resume."""
    if not resume_text.strip() or not available_skills:
        return []

    if not settings.OPENAI_API_KEY:
        return _fallback_skill_match(resume_text, available_skills)

    system_prompt = (
        "You extract canonical skills from a CV. "
        "Return strict JSON only in this shape: "
        '{"skills": ["Skill 1", "Skill 2"]}. '
        "Only return skill names that exist in the allowed list exactly."
    )
    user_prompt = (
        "Allowed skills:\n"
        + "\n".join(f"- {skill}" for skill in available_skills)
        + "\n\nCV text:\n"
        + resume_text[:12000]
    )
    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(str(content))
        raw_skills = parsed.get("skills") or []
        if not isinstance(raw_skills, list):
            return _fallback_skill_match(resume_text, available_skills)
        allowed_set = set(available_skills)
        matched = []
        seen = set()
        for item in raw_skills:
            name = str(item).strip()
            if name in allowed_set and name not in seen:
                seen.add(name)
                matched.append(name)
        return matched
    except Exception as exc:
        print(f"Failed to extract skills from CV with OpenAI: {exc}")
        return _fallback_skill_match(resume_text, available_skills)


def _fallback_skill_match(resume_text: str, available_skills: Sequence[str]) -> List[str]:
    """Naive fallback matcher when AI is unavailable."""
    lower_text = resume_text.lower()
    matched = []
    for skill in available_skills:
        if skill.lower() in lower_text:
            matched.append(skill)
    return matched


async def transcribe_audio_to_text(
    audio_bytes: bytes,
    mime_type: Optional[str] = None,
) -> str:
    """Transcribe audio bytes with OpenAI audio transcription API."""
    if not settings.OPENAI_API_KEY:
        return ""

    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    data = {"model": settings.OPENAI_AUDIO_MODEL}
    files = {"file": ("voice-note", audio_bytes, mime_type or "audio/ogg")}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers=headers,
                data=data,
                files=files,
            )
            resp.raise_for_status()
            payload = resp.json()
            text = str(payload.get("text") or "").strip()
            return text
    except Exception as exc:
        print(f"OpenAI audio transcription failed: {exc}")
        return ""
