"""Data access layer for the Project model."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    @staticmethod
    async def create(db: AsyncSession, *, name: str, description: str | None) -> Project:
        project = Project(name=name, description=description)
        try:
            db.add(project)
            await db.commit()
            await db.refresh(project)
            return project
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_by_id(db: AsyncSession, project_id: int) -> Project | None:
        return await db.get(Project, project_id)

    @staticmethod
    async def get_all(
        db: AsyncSession,
        *,
        limit: int,
        offset: int,
        search: str | None,
        sort_by: str,
        sort_order: str,
    ) -> tuple[list[Project], int]:
        filters = [Project.name.ilike(f"%{search}%")] if search else []

        total = await db.scalar(select(func.count()).select_from(Project).where(*filters)) or 0

        sort_column = getattr(Project, sort_by)
        sort_column = sort_column.asc() if sort_order == "asc" else sort_column.desc()

        projects = (
            await db.scalars(
                select(Project).where(*filters).order_by(sort_column).offset(offset).limit(limit)
            )
        ).all()

        return list(projects), total
