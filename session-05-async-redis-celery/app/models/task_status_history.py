"""The TaskStatusHistory model for tracking task status changes."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import TaskStatus

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskStatusHistory(Base, TimestampMixin):
    __tablename__ = "task_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", create_type=False), nullable=False
    )
    new_status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", create_type=False), nullable=False
    )
    changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    task: Mapped["Task"] = relationship()
    changed_by: Mapped["User | None"] = relationship(foreign_keys=[changed_by_id])
