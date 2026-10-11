"""Data access layer for the Workspace and WorkspaceUser models."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace
from app.models.workspace_user import WorkspaceUser


class WorkspaceRepository:
    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        name: str,
        slug: str,
        description: str | None = None,
        workspace_id: int | None = None,
    ) -> Workspace:
        """Create a workspace record."""
        workspace = (
            Workspace(id=workspace_id, name=name, slug=slug, description=description)
            if workspace_id is not None
            else Workspace(name=name, slug=slug, description=description)
        )
        try:
            db.add(workspace)
            await db.commit()
            await db.refresh(workspace)
            return workspace
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_by_id(db: AsyncSession, workspace_id: int) -> Workspace | None:
        """Retrieve a workspace by its ID."""
        return await db.get(Workspace, workspace_id)

    @staticmethod
    async def get_by_slug(db: AsyncSession, slug: str) -> Workspace | None:
        """Retrieve a workspace by its unique slug."""
        result = await db.execute(select(Workspace).where(Workspace.slug == slug))
        return result.scalar_one_or_none()

    @staticmethod
    async def add_user_to_workspace(
        db: AsyncSession, *, workspace_id: int, user_id: int
    ) -> WorkspaceUser:
        """Associate a user with a workspace."""
        membership = WorkspaceUser(workspace_id=workspace_id, user_id=user_id)
        try:
            db.add(membership)
            await db.commit()
            await db.refresh(membership)
            return membership
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def is_user_in_workspace(db: AsyncSession, *, workspace_id: int, user_id: int) -> bool:
        """Check if a user is a member of the given workspace."""
        result = await db.scalar(
            select(func.count())
            .select_from(WorkspaceUser)
            .where(
                WorkspaceUser.workspace_id == workspace_id,
                WorkspaceUser.user_id == user_id,
            )
        )
        return bool(result and result > 0)

    @staticmethod
    async def get_user_workspaces(db: AsyncSession, user_id: int) -> list[Workspace]:
        """List all workspaces a user belongs to."""
        query = (
            select(Workspace)
            .join(WorkspaceUser, Workspace.id == WorkspaceUser.workspace_id)
            .where(WorkspaceUser.user_id == user_id)
        )
        result = await db.scalars(query)
        return list(result.all())
