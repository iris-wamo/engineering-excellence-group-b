"""The ProjectUser membership model, joining users to projects with a role."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ProjectRole

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class ProjectUser(Base):
    """Membership link between users and projects (many to many), including ownership."""

    __tablename__ = "project_user"
    __table_args__ = (
        # Only rows where role = 'owner' are checked for uniqueness,
        # ensuring a project cannot have more than one owner.
        Index(
            "one_owner_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
    )

    # Composite primary key: a user cannot be added to the same project twice.
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )

    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role"),
        nullable=False,
        server_default=ProjectRole.member.value,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")
