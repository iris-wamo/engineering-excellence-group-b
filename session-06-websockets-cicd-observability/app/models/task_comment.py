from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskComment(Base, TimestampMixin):
    __tablename__ = "task_comment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Comments are always read per task, so the listing query filters on this column.
    task_id: Mapped[int] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    task: Mapped["Task"] = relationship()
    user: Mapped["User"] = relationship()
