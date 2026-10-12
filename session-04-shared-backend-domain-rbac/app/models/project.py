"""The Project model."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.project_user import ProjectUser
    from app.models.task import Task
    from app.models.workspace import Workspace


class Project(Base, TimestampMixin):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_project_workspace_slug"),
        UniqueConstraint("id", "workspace_id", name="uq_project_id_workspace_id"),
        Index("ix_project_slug", "slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    workspace_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workspace.id", ondelete="CASCADE"),
        nullable=False,
        server_default="1",
        default=1,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="[Task.project_id, Task.workspace_id]",
        overlaps="tasks,workspace",
    )
    members: Mapped[list["ProjectUser"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
