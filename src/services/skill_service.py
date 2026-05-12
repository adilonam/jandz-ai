"""Operations for skill catalog and user-skill relationships."""

from typing import List, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.skill import Skill
from src.models.whatsapp_user import WhatsAppUser


async def list_skills(session: AsyncSession) -> List[Skill]:
    """Return all canonical skills ordered by name."""
    result = await session.scalars(
        select(Skill).options(selectinload(Skill.users)).order_by(Skill.name.asc())
    )
    return list(result.all())


async def set_user_skills_by_names(
    session: AsyncSession,
    user: WhatsAppUser,
    skill_names: Sequence[str],
) -> List[Skill]:
    """Replace user skills with canonical entries matching provided names."""
    cleaned_names = [name.strip() for name in skill_names if name.strip()]
    if not cleaned_names:
        user.skills = []
        await session.commit()
        await session.refresh(user)
        return []

    result = await session.scalars(select(Skill).where(Skill.name.in_(cleaned_names)))
    matched_skills = list(result.all())

    by_name = {skill.name: skill for skill in matched_skills}
    deduped_in_order = [by_name[name] for name in cleaned_names if name in by_name]

    seen_ids = set()
    unique_skills: List[Skill] = []
    for skill in deduped_in_order:
        if skill.id not in seen_ids:
            seen_ids.add(skill.id)
            unique_skills.append(skill)

    user.skills = unique_skills
    await session.commit()
    await session.refresh(user)
    return unique_skills
