"""Pydantic schemas used by API routes."""

from typing import Optional

from pydantic import BaseModel, Field


class EchoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=512)


class CoresignalJobsSearchRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    location: str = Field(default="", max_length=256)
    work_mode: str = Field(default="", max_length=32)
    limit: Optional[int] = Field(default=None, ge=1, le=100)
