"""The Workspace model for multi-tenancy."""

from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task
    from app.models.workspace_user import WorkspaceUser


class Workspace(Base, TimestampMixin):
    """A tenant workspace that groups projects, tasks, and member users."""

    __tablename__ = "workspace"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspace_slug"),
        Index("ix_workspace_slug", "slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    projects: Mapped[list["Project"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    members: Mapped[list["WorkspaceUser"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
