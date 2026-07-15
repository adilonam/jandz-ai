"""Direct CoreSignal Multi-source Jobs REST API client."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from src.config import settings

CORESIGNAL_BASE_URL = "https://api.coresignal.com/cdapi/v2/job_multi_source"
SEARCH_URL = f"{CORESIGNAL_BASE_URL}/search/es_dsl"
COLLECT_URL = f"{CORESIGNAL_BASE_URL}/collect/{{job_id}}"

COLLECT_FIELDS = [
    "id",
    "title",
    "company_name",
    "location",
    "country",
    "city",
    "external_url",
    "description",
    "accepts_remote",
    "employment_type",
]

DEFAULT_SEARCH_LIMIT = 20
REQUEST_TIMEOUT = 60.0


def _auth_headers() -> Dict[str, str]:
    if not settings.CORESIGNAL_API_KEY:
        raise ValueError("CORESIGNAL_API_KEY is missing.")
    return {
        "accept": "application/json",
        "apikey": settings.CORESIGNAL_API_KEY,
        "Content-Type": "application/json",
    }


def build_jobs_es_dsl(
    title: str,
    location: str = "",
    work_mode: str = "",
) -> Dict[str, Any]:
    """Build an Elasticsearch DSL body for multi-source job search."""
    must: List[Dict[str, Any]] = []
    safe_title = (title or "").strip()
    if safe_title:
        must.append({"match": {"title": safe_title}})

    safe_location = (location or "").strip()
    if safe_location:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"location": safe_location}},
                        {"match": {"country": safe_location}},
                        {"match": {"city": safe_location}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    mode = (work_mode or "").strip().lower()
    if mode == "remote":
        must.append({"term": {"accepts_remote": True}})
    elif mode == "onsite":
        must.append({"term": {"accepts_remote": False}})

    if not must:
        must.append({"match_all": {}})

    return {"query": {"bool": {"must": must}}}


def _normalize_job(raw: Dict[str, Any]) -> Dict[str, Any]:
    external_url = str(raw.get("external_url") or "").strip()
    return {
        "id": raw.get("id"),
        "title": str(raw.get("title") or "").strip(),
        "company_name": str(raw.get("company_name") or "").strip(),
        "location": str(raw.get("location") or "").strip(),
        "country": str(raw.get("country") or "").strip(),
        "city": str(raw.get("city") or "").strip(),
        "external_url": external_url,
        "url": external_url,
        "description": str(raw.get("description") or "").strip(),
        "accepts_remote": raw.get("accepts_remote"),
        "employment_type": str(raw.get("employment_type") or "").strip(),
    }


def _job_summary_for_history(job: Dict[str, Any]) -> Dict[str, Any]:
    description = str(job.get("description") or "")
    return {
        "id": job.get("id"),
        "title": job.get("title"),
        "company_name": job.get("company_name"),
        "location": job.get("location"),
        "country": job.get("country"),
        "url": job.get("url") or job.get("external_url"),
        "accepts_remote": job.get("accepts_remote"),
        "employment_type": job.get("employment_type"),
        "description": description[:280],
    }


async def search_job_ids(
    es_dsl: Dict[str, Any],
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """POST search/es_dsl and return matching job IDs plus response metadata."""
    items_per_page = max(1, min(int(limit), 1000))
    headers = _auth_headers()
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    try:
        response = await http.post(
            SEARCH_URL,
            headers=headers,
            params={"items_per_page": items_per_page},
            json=es_dsl,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("CoreSignal search returned an unexpected payload shape.")
        job_ids = [item for item in payload if item is not None]
        return {
            "job_ids": job_ids,
            "total_results": response.headers.get("x-total-results"),
            "items_per_page": response.headers.get("x-items-per-page"),
            "credits_remaining": response.headers.get("x-credits-remaining"),
        }
    except httpx.HTTPStatusError as exc:
        details = exc.response.text[:500]
        raise RuntimeError(
            f"CoreSignal search returned HTTP {exc.response.status_code}: {details}"
        ) from exc
    finally:
        if owns_client:
            await http.aclose()


async def collect_job(
    job_id: Any,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """GET collect/{job_id} and return a normalized job row."""
    headers = {
        "accept": "application/json",
        "apikey": settings.CORESIGNAL_API_KEY,
    }
    if not settings.CORESIGNAL_API_KEY:
        raise ValueError("CORESIGNAL_API_KEY is missing.")

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    params = [("fields", field) for field in COLLECT_FIELDS]

    try:
        response = await http.get(
            COLLECT_URL.format(job_id=job_id),
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"CoreSignal collect returned unexpected payload for id={job_id}.")
        return _normalize_job(payload)
    except httpx.HTTPStatusError as exc:
        details = exc.response.text[:500]
        raise RuntimeError(
            f"CoreSignal collect returned HTTP {exc.response.status_code}: {details}"
        ) from exc
    finally:
        if owns_client:
            await http.aclose()


async def search_jobs(
    *,
    title: str,
    location: str = "",
    work_mode: str = "",
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Search job IDs then collect full rows needed by reply formatters."""
    search_limit = limit if limit is not None else DEFAULT_SEARCH_LIMIT
    search_limit = max(1, min(int(search_limit), 1000))
    es_dsl = build_jobs_es_dsl(title=title, location=location, work_mode=work_mode)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            search_meta = await search_job_ids(es_dsl, limit=search_limit, client=client)
            job_ids = search_meta["job_ids"]
            collected = await asyncio.gather(
                *[collect_job(job_id, client=client) for job_id in job_ids],
                return_exceptions=True,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"CoreSignal request failed: {exc}") from exc

    jobs: List[Dict[str, Any]] = []
    collect_errors: List[str] = []
    for result in collected:
        if isinstance(result, Exception):
            collect_errors.append(str(result))
            continue
        jobs.append(result)

    history_payload = {
        "request": {
            "title": title,
            "location": location,
            "work_mode": work_mode,
            "limit": search_limit,
            "es_dsl": es_dsl,
        },
        "search": {
            "job_ids": job_ids,
            "total_results": search_meta.get("total_results"),
            "items_per_page": search_meta.get("items_per_page"),
            "credits_remaining": search_meta.get("credits_remaining"),
        },
        "jobs": [_job_summary_for_history(job) for job in jobs],
        "collect_errors": collect_errors[:10],
        "jobs_count": len(jobs),
    }
    return {"jobs": jobs, "history_payload": history_payload, "es_dsl": es_dsl}
