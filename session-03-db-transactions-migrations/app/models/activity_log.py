"""The ActivityLog model for auditing system events."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class ActivityLog(Base, TimestampMixin):
    __tablename__ = "activity_log"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('task', 'project', 'user')",
            name="ck_activity_log_entity_type",
        ),
        Index("ix_activity_log_entity", "entity_type", "entity_id"),
        Index("ix_activity_log_actor_id", "actor_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    actor: Mapped["User | None"] = relationship()
