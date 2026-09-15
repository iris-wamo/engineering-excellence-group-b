"""The TaskAssignmentHistory model for tracking task assignment changes."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskAssignmentHistory(Base, TimestampMixin):
    __tablename__ = "task_assignment_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    new_assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    task: Mapped["Task"] = relationship()
    previous_assignee: Mapped["User | None"] = relationship(foreign_keys=[previous_assignee_id])
    new_assignee: Mapped["User | None"] = relationship(foreign_keys=[new_assignee_id])
    assigned_by: Mapped["User | None"] = relationship(foreign_keys=[assigned_by_id])
