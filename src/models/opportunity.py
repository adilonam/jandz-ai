"""Opportunity model for education and job suggestions."""

from datetime import datetime
from typing import Any, List, Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.chat_user import ChatUser


class Opportunity(Base):
    """A single education or job opportunity shown on a public detail page."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    organization: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deadline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    funding_or_salary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    eligibility: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    apply_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tips: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    chat_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chat_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chat_user: Mapped[Optional["ChatUser"]] = relationship(lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def tips_as_list(self) -> List[str]:
        """Normalize tips JSON/text into a list of display strings."""
        if self.tips is None:
            return []
        if isinstance(self.tips, list):
            return [str(item).strip() for item in self.tips if str(item).strip()]
        if isinstance(self.tips, str) and self.tips.strip():
            return [self.tips.strip()]
        return []
