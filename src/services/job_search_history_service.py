"""Service helpers for persisting MCP job search history."""

from typing import Any, Dict, List

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.job_search_history import JobSearchHistory


async def create_job_search_history(
    session: AsyncSession,
    prompt_query: str,
    response_payload: Dict[str, Any],
    provider: str = "coresignal_mcp",
) -> JobSearchHistory:
    """Create and persist one job search history row."""
    row = JobSearchHistory(
        provider=provider,
        prompt_query=prompt_query,
        response_payload=response_payload,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_job_search_history(
    session: AsyncSession,
    limit: int = 100,
) -> List[JobSearchHistory]:
    """Return newest MCP job search history rows first."""
    stmt = (
        select(JobSearchHistory)
        .order_by(desc(JobSearchHistory.created_at))
        .limit(limit)
    )
    rows = await session.scalars(stmt)
    return list(rows.all())


async def count_job_search_history(session: AsyncSession) -> int:
    """Return total number of saved MCP job search history rows."""
    stmt = select(func.count(JobSearchHistory.id))
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)
