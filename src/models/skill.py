"""Skill and user-skill association models."""

from typing import List, TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Integer, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.chat_user import ChatUser

chat_user_skills = Table(
    "chat_user_skills",
    Base.metadata,
    Column("user_id", ForeignKey("chat_users.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("user_id", "skill_id", name="uq_chat_user_skill"),
)


class Skill(Base):
    """Canonical skill entry used for user matching."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    users: Mapped[List["ChatUser"]] = relationship(
        secondary=chat_user_skills,
        back_populates="skills",
        lazy="selectin",
    )
