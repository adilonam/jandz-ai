"""Pydantic schemas used by API routes."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EchoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=512)


class CoresignalJobsSearchRequest(BaseModel):
    prompt: str = Field(default="", max_length=1024)
    title: str = Field(default="", max_length=256)
    location: str = Field(default="", max_length=256)
    work_mode: str = Field(default="", max_length=32)
    limit: Optional[int] = Field(default=None, ge=1, le=100)
    after: Optional[str] = Field(default=None, max_length=512)
    es_dsl: Optional[Dict[str, Any]] = None
    collect: bool = Field(default=True)


class CoresignalCollectRequest(BaseModel):
    job_ids: List[int] = Field(..., min_length=1, max_length=50)


class JobSearchParamsExtractRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1024)


class JobSearchParams(BaseModel):
    title: str = Field(default="", max_length=256)
    location: str = Field(default="", max_length=256)
    country: str = Field(default="", max_length=256)
    work_mode: str = Field(default="", max_length=32)
    limit: int = Field(default=5, ge=1, le=100)
