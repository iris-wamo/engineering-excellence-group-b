from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate


class ProjectService:
    @staticmethod
    def create_project(db: Session, payload: ProjectCreate) -> Project:
        return ProjectRepository.create(db, name=payload.name, description=payload.description)

    @staticmethod
    def get_project(db: Session, project_id: int) -> Project:
        project = ProjectRepository.get_by_id(db, project_id)
        if project is None:
            raise NotFoundError(
                "Project not found",
                details=[{"field": "project_id", "message": "Project does not exist"}],
            )

        return project

    @staticmethod
    def list_projects(
        db: Session,
        *,
        page: int,
        page_size: int,
        search: str | None,
        sort_by: str,
        sort_order: str,
    ) -> tuple[list[Project], int]:
        offset = (page - 1) * page_size
        return ProjectRepository.get_all(
            db,
            limit=page_size,
            offset=offset,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
