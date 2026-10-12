"""The User model."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project_user import ProjectUser
    from app.models.task import Task


class User(Base, TimestampMixin):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Nullable because users created before authentication existed (and seeded rows) have
    # no password; those accounts simply cannot log in until they sign up with one.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    tasks: Mapped[list["Task"]] = relationship(back_populates="assignee")
    memberships: Mapped[list["ProjectUser"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
