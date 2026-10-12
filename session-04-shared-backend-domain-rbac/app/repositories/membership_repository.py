"""Data access layer for reading a user's project roles."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole
from app.models.project_user import ProjectUser


class MembershipRepository:
    @staticmethod
    async def get_role_in_project(
        db: AsyncSession, *, user_id: int, project_id: int
    ) -> ProjectRole | None:
        """Return the user's role in one project, or None if they are not a member."""
        role: ProjectRole | None = await db.scalar(
            select(ProjectUser.role).where(
                ProjectUser.user_id == user_id,
                ProjectUser.project_id == project_id,
            )
        )
        return role

    @staticmethod
    async def get_all_roles(db: AsyncSession, *, user_id: int) -> set[ProjectRole]:
        """Return every distinct role the user holds across all projects."""
        roles = await db.scalars(
            select(ProjectUser.role).where(ProjectUser.user_id == user_id).distinct()
        )
        return set(roles.all())
