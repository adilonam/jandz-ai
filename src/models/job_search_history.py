"""Search history model for MCP job lookups."""

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base


class JobSearchHistory(Base):
    """Stores each MCP search prompt and its raw JSON response."""

    __tablename__ = "job_search_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, default="coresignal_api")
    prompt_query: Mapped[str] = mapped_column(Text, nullable=False)
    response_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
