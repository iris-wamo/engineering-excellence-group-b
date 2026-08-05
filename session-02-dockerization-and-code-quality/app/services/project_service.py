from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate


class ProjectService:
    @staticmethod
    async def create_project(db: AsyncSession, payload: ProjectCreate) -> Project:
        return await ProjectRepository.create(
            db, name=payload.name, description=payload.description
        )

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
