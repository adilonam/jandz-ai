"""Minimal FastAPI application."""

from typing import Dict

from pydantic import BaseModel, Field
from fastapi import FastAPI

app = FastAPI(
    title="hire-chat API",
    version="0.1.0",
    description="Basic FastAPI starter.",
)


@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "hire-chat API"}


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


class EchoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=512)


@app.post("/echo")
async def echo(body: EchoRequest) -> Dict[str, str]:
    return {"echo": body.text}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
