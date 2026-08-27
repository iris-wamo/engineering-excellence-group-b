"""Project CRUD endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.project import Project
from app.schemas import ProjectCreate, ProjectListResponse, ProjectResponse
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> Project:
    """Create a new project."""
    return await ProjectService.create_project(db, project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    sort_by: Literal["name", "created_at", "updated_at"] = "created_at",
    sort_order: Literal["asc", "desc"] = "asc",
) -> ProjectListResponse:
    """List projects, paginated and optionally filtered by name and sorted."""
    projects, total = await ProjectService.list_projects(
        db,
        page=page,
        page_size=page_size,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(project) for project in projects],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    db: Annotated[AsyncSession, Depends(get_db)], project_id: int = Path(gt=0)
) -> Project:
    """Retrieve a project by ID."""
    return await ProjectService.get_project(db, project_id)
