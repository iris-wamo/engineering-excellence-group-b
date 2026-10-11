"""Business logic for project management."""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import ProjectRole
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate


def _slugify(name: str) -> str:
    """Convert a project name into a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class ProjectService:
    @staticmethod
    async def create_project(
        db: AsyncSession, payload: ProjectCreate, *, created_by_id: int | None = None
    ) -> Project:
        slug = _slugify(payload.name)
        project = await ProjectRepository.create(
            db, name=payload.name, slug=slug, description=payload.description
        )

        # Roles are per project, so without this the creator would hold no role in the
        # project they just made and could not add tasks to it.
        if created_by_id is not None:
            db.add(
                ProjectUser(project_id=project.id, user_id=created_by_id, role=ProjectRole.owner)
            )
            await db.commit()
            await db.refresh(project)

        return project

    @staticmethod
    async def get_project(db: AsyncSession, project_id: int) -> Project:
        project = await ProjectRepository.get_by_id(db, project_id)
        if project is None:
            raise NotFoundError(
                "Project not found",
                details=[{"field": "project_id", "message": "Project does not exist"}],
            )

        return project

    @staticmethod
    async def list_projects(
        db: AsyncSession,
        *,
        page: int,
        page_size: int,
        search: str | None,
        sort_by: str,
        sort_order: str,
    ) -> tuple[list[Project], int]:
        offset = (page - 1) * page_size
        return await ProjectRepository.get_all(
            db,
            limit=page_size,
            offset=offset,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
