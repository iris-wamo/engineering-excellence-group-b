from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project


class ProjectRepository:
    @staticmethod
    def create(db: Session, *, name: str, description: str | None) -> Project:
        project = Project(name=name, description=description)
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def get_by_id(db: Session, project_id: int) -> Project | None:
        return db.get(Project, project_id)

    @staticmethod
    def get_all(
        db: Session,
        *,
        limit: int,
        offset: int,
        search: str | None,
        sort_by: str,
        sort_order: str,
    ) -> tuple[list[Project], int]:
        filters = [Project.name.ilike(f"%{search}%")] if search else []

        total = db.scalar(select(func.count()).select_from(Project).where(*filters)) or 0

        sort_column = getattr(Project, sort_by)
        sort_column = sort_column.asc() if sort_order == "asc" else sort_column.desc()

        projects = db.scalars(
            select(Project).where(*filters).order_by(sort_column).offset(offset).limit(limit)
        ).all()

        return list(projects), total
