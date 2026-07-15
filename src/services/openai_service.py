"""OpenAI integration service."""

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import httpx

from src.config import settings
from src.prompts import build_opportunity_prompts


@dataclass
class OpportunityGenerationResult:
    """Structured AI opportunities with a text fallback when JSON parse fails."""

    opportunities: List[Dict[str, Any]] = field(default_factory=list)
    fallback_text: str = ""



async def generate_openai_reply(user_text: str) -> str:
    """Generate a Telegram response from OpenAI."""
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


def _parse_opportunities_json(raw_content: str) -> List[Dict[str, Any]]:
    """Extract an opportunities array from model JSON (dict or bare list)."""
    content = raw_content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        parsed = json.loads(content)
    except Exception:
        # Best-effort: pull the outermost JSON object/array from mixed prose.
        start_obj = content.find("{")
        start_arr = content.find("[")
        starts = [i for i in (start_obj, start_arr) if i >= 0]
        if not starts:
            return []
        start = min(starts)
        end_obj = content.rfind("}")
        end_arr = content.rfind("]")
        end = max(end_obj, end_arr)
        if end <= start:
            return []
        try:
            parsed = json.loads(content[start : end + 1])
        except Exception:
            return []

    items: Any
    if isinstance(parsed, dict):
        items = parsed.get("opportunities")
        if items is None:
            items = parsed.get("items") or parsed.get("results")
    elif isinstance(parsed, list):
        items = parsed
    else:
        return []

    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


async def generate_opportunities(
    opportunity_type: str,
    skill_names: Sequence[str],
    limit: Optional[int] = None,
    request_text: Optional[str] = None,
    location: Optional[str] = None,
) -> OpportunityGenerationResult:
    """Suggest education or job opportunities as structured JSON when possible."""
    max_items = limit if limit is not None else 5
    kind = "education" if opportunity_type == "education" else "job"
    skills_label = ", ".join(name.strip() for name in skill_names if name.strip()) or (
        "general profile (skills not extracted yet)"
    )
    error_fallback = (
        f"I could not list {kind} opportunities right now. "
        "Please try again in a moment, or reply with education or jobs."
    )

    if not settings.OPENAI_API_KEY:
        return OpportunityGenerationResult(
            fallback_text=(
                f"I am not configured yet to list {kind} opportunities. "
                "Please set OPENAI_API_KEY."
            )
        )

    prompts = build_opportunity_prompts(
        opportunity_type,
        skills_label=skills_label,
        max_items=max_items,
        user_request=request_text,
        location=location,
    )

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": prompts.system},
            {"role": "user", "content": prompts.user},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
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
            if resp.status_code >= 400:
                # Some models reject response_format; retry without it.
                payload.pop("response_format", None)
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
            resp.raise_for_status()
            data = resp.json()
        content = str(data["choices"][0]["message"]["content"]).strip()
        if not content:
            return OpportunityGenerationResult(fallback_text=error_fallback)

        opportunities = _parse_opportunities_json(content)
        if opportunities:
            return OpportunityGenerationResult(opportunities=opportunities[:max_items])

        # Graceful fallback: send raw model text when it is not empty JSON prose.
        if content.lstrip().startswith(("{", "[")):
            return OpportunityGenerationResult(fallback_text=error_fallback)
        return OpportunityGenerationResult(fallback_text=content)
    except Exception as exc:
        print(f"OpenAI opportunity listing failed: {exc}")
        return OpportunityGenerationResult(fallback_text=error_fallback)


async def generate_opportunities_reply(
    opportunity_type: str,
    skill_names: Sequence[str],
    limit: Optional[int] = None,
    request_text: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Compatibility wrapper returning free-text opportunity suggestions."""
    result = await generate_opportunities(
        opportunity_type,
        skill_names,
        limit=limit,
        request_text=request_text,
        location=location,
    )
    if result.fallback_text:
        return result.fallback_text
    lines = []
    for index, item in enumerate(result.opportunities, start=1):
        title = str(item.get("title") or f"Opportunity {index}").strip()
        org = str(item.get("organization") or "").strip()
        url = str(item.get("apply_url") or item.get("source_url") or "").strip()
        heading = f"{index}. {title}" + (f" — {org}" if org else "")
        lines.append(heading)
        if url:
            lines.append(url)
        lines.append("")
    return "\n".join(lines).rstrip() or (
        "I could not list opportunities right now. Please try again."
    )


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


def _safe_json_loads(raw_content: str) -> Optional[dict]:
    """Parse JSON payload and tolerate fenced markdown wrappers."""
    content = raw_content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _normalize_full_name(name: str) -> Optional[str]:
    candidate = " ".join(name.strip().split())
    if not candidate or len(candidate) < 4 or len(candidate) > 120:
        return None

    if not re.fullmatch(r"[A-Za-z][A-Za-z\s\-'.]{2,119}", candidate):
        return None

    blocked = {
        "curriculum vitae",
        "resume",
        "cv",
        "professional summary",
        "experience",
        "education",
    }
    if candidate.lower() in blocked:
        return None

    parts = [p for p in candidate.split(" ") if p]
    if len(parts) < 2:
        return None
    return candidate


def _fallback_extract_full_name_from_resume_text(resume_text: str) -> Optional[str]:
    for raw_line in resume_text.splitlines()[:12]:
        line = raw_line.strip()
        if not line:
            continue
        normalized = _normalize_full_name(line)
        if normalized:
            return normalized
    return None


async def extract_full_name_from_resume(resume_text: str) -> Optional[str]:
    """Extract candidate full name from parsed CV text."""
    if not resume_text.strip():
        return None

    if not settings.OPENAI_API_KEY:
        return _fallback_extract_full_name_from_resume_text(resume_text)

    system_prompt = (
        "Extract the candidate full name from CV text. "
        "Return strict JSON only in this shape: {\"full_name\": \"First Last\"}. "
        "If unknown, return {\"full_name\": \"\"}."
    )
    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": resume_text[:12000]},
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
            content = str(data["choices"][0]["message"]["content"])
    except Exception as exc:
        print(f"Failed to extract full name from CV text with OpenAI: {exc}")
        return _fallback_extract_full_name_from_resume_text(resume_text)

    parsed = _safe_json_loads(content)
    if not parsed:
        return _fallback_extract_full_name_from_resume_text(resume_text)

    return _normalize_full_name(str(parsed.get("full_name") or ""))


async def extract_full_name_from_resume_pdf(pdf_bytes: bytes) -> Optional[str]:
    """Extract candidate full name from resume PDF bytes."""
    if not pdf_bytes or not settings.OPENAI_API_KEY:
        return None

    encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
    system_prompt = (
        "Extract the candidate full name from the attached CV PDF. "
        "Return strict JSON only in this shape: {\"full_name\": \"First Last\"}. "
        "If unknown, return {\"full_name\": \"\"}."
    )
    payload = {
        "model": settings.OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": "resume.pdf",
                        "file_data": f"data:application/pdf;base64,{encoded_pdf}",
                    }
                ],
            },
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/responses",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(f"Failed to extract full name from CV PDF with OpenAI: {exc}")
        return None

    raw_content = str(data.get("output_text") or "").strip()
    parsed = _safe_json_loads(raw_content)
    if not parsed:
        return None

    return _normalize_full_name(str(parsed.get("full_name") or ""))


async def extract_skills_from_resume_pdf(
    pdf_bytes: bytes,
    available_skills: Sequence[str],
) -> List[str]:
    """Use OpenAI to infer canonical skills from PDF bytes (works for scanned/image CVs)."""
    if not pdf_bytes or not available_skills or not settings.OPENAI_API_KEY:
        return []

    encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
    system_prompt = (
        "You extract canonical skills from CV PDFs. "
        "Return strict JSON only in this shape: "
        '{"skills": ["Skill 1", "Skill 2"]}. '
        "Only return skill names that exist in the allowed list exactly."
    )
    user_prompt = (
        "Allowed skills:\n"
        + "\n".join(f"- {skill}" for skill in available_skills)
        + "\n\nAnalyze the attached resume PDF and return matched skills."
    )
    payload = {
        "model": settings.OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                    {
                        "type": "input_file",
                        "filename": "resume.pdf",
                        "file_data": f"data:application/pdf;base64,{encoded_pdf}",
                    },
                ],
            },
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/responses",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(f"Failed to extract skills from PDF bytes with OpenAI: {exc}")
        return []

    raw_content = str(data.get("output_text") or "").strip()
    if not raw_content:
        return []

    parsed = _safe_json_loads(raw_content)
    if not parsed:
        return []

    raw_skills = parsed.get("skills") or []
    if not isinstance(raw_skills, list):
        return []

    allowed_set = set(available_skills)
    matched = []
    seen = set()
    for item in raw_skills:
        name = str(item).strip()
        if name in allowed_set and name not in seen:
            seen.add(name)
            matched.append(name)
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
