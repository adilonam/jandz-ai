"""Pydantic schemas used by API routes."""

from pydantic import BaseModel, Field


class EchoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=512)


class McpPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
