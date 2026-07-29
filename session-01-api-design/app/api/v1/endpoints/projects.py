"""Project CRUD endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import ProjectCreate, ProjectListResponse, ProjectResponse
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
    responses={
        201: {
            "description": "Project created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "name": "PeopleUp",
                        "description": (
                            "Your 360 HRM solution - unified talent "
                            "management with real-time insights"
                        ),
                        "created_at": "2026-07-26T10:00:00+00:00",
                        "updated_at": "2026-07-26T10:00:00+00:00",
                    }
                }
            },
        },
        422: {"description": "Validation error (empty name, too long, etc)"},
    },
)
def create_project(project: ProjectCreate, db: Annotated[Session, Depends(get_db)]):
    """Create a new project."""
    return ProjectService.create_project(db, project)


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List all projects",
    responses={
        200: {
            "description": "Projects retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "id": 1,
                                "name": "PeopleUp",
                                "description": (
                                    "Your 360 HRM solution - unified talent "
                                    "management with real-time insights"
                                ),
                                "created_at": "2026-07-20T08:30:00+00:00",
                                "updated_at": "2026-07-26T14:15:00+00:00",
                            },
                            {
                                "id": 2,
                                "name": "Actovio",
                                "description": (
                                    "Track productivity with intelligent activity "
                                    "monitoring and engagement analytics"
                                ),
                                "created_at": "2026-07-22T11:45:00+00:00",
                                "updated_at": "2026-07-26T10:20:00+00:00",
                            },
                        ],
                        "total": 2,
                        "page": 1,
                        "page_size": 10,
                    }
                }
            },
        }
    },
)
def list_projects(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    sort_by: Literal["name", "created_at", "updated_at"] = "created_at",
    sort_order: Literal["asc", "desc"] = "asc",
) -> ProjectListResponse:
    """List projects, paginated and optionally filtered by name and sorted."""
    projects, total = ProjectService.list_projects(
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


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project by ID",
    responses={
        200: {
            "description": "Project retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "name": "PeopleUp",
                        "description": (
                            "Your 360 HRM solution - unified talent "
                            "management with real-time insights"
                        ),
                        "created_at": "2026-07-20T08:30:00+00:00",
                        "updated_at": "2026-07-26T14:15:00+00:00",
                    }
                }
            },
        },
        404: {"description": "Project not found"},
        422: {"description": "Invalid project ID"},
    },
)
def get_project(db: Annotated[Session, Depends(get_db)], project_id: int = Path(gt=0)):
    """Retrieve a project by ID."""
    return ProjectService.get_project(db, project_id)
