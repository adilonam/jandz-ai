"""FastAPI application factory and router registration."""

from fastapi import FastAPI

from src.config import settings
from src.db import init_db
from src.routers.core import router as core_router
from src.routers.whatsapp import router as whatsapp_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
)

app.include_router(core_router)
app.include_router(whatsapp_router)


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
