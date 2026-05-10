"""Basic health and utility routes."""

from fastapi import APIRouter
from typing import Dict

from src.schemas import EchoRequest

router = APIRouter(tags=["core"])


@router.get("/")
async def root() -> Dict[str, str]:
    return {"message": "jandz-ai API"}


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.post("/echo")
async def echo(body: EchoRequest) -> Dict[str, str]:
    return {"echo": body.text}
