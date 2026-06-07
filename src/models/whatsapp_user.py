"""WhatsApp user model."""

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base
from src.models.skill import whatsapp_user_skills

if TYPE_CHECKING:
    from src.models.conversation_message import ConversationMessage
    from src.models.skill import Skill


class WhatsAppUser(Base):
    """User identified by WhatsApp phone number."""

    __tablename__ = "whatsapp_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    resume_pdf: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    skills: Mapped[List["Skill"]] = relationship(
        secondary=whatsapp_user_skills,
        back_populates="users",
        lazy="selectin",
    )
    conversation_messages: Mapped[List["ConversationMessage"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
