"""FastAPI application factory and router registration."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.db import init_db
from src.routers.core import router as core_router
from src.routers.telegram import router as telegram_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)

app.include_router(core_router)
app.include_router(telegram_router)


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
