"""Project CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.schemas import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectRead,
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
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    """Create a new project.

    Creates a new project with the provided name and optional description.
    The project is immediately available for use and assigned a unique ID.

    Args:
        project: Project data (name and optional description).
        db: Database session dependency.

    Returns:
        The created project with generated id, created_at, and updated_at timestamps.

    Raises:
        400: If the project name is empty or exceeds max length.
    """
    db_project = Project(name=project.name, description=project.description)
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


@router.get(
    "",
    response_model=list[ProjectRead],
    summary="List all projects",
    responses={
        200: {
            "description": "Projects retrieved successfully",
            "content": {
                "application/json": {
                    "example": [
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
                    ]
                }
            },
        }
    },
)
def list_projects(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "asc",
    db: Session = Depends(get_db),
):
    """List all projects with pagination, filtering, and sorting.

    Retrieve a paginated list of projects with optional filtering by name and sorting.

    Query Examples:
    - `/projects` - Get first 100 projects, sorted by creation date
    - `/projects?limit=10&sort_by=name` - Get first 10 projects sorted by name
    - `/projects?search=marketing` - Find projects with "marketing" in the name
    - `/projects?sort_order=desc` - Sort by creation date, newest first

    Args:
        skip: Number of projects to skip (default 0, must be >= 0).
        limit: Maximum number of projects to return (default 100, must be 1-100).
        search: Filter projects by name (case-insensitive partial match).
        sort_by: Sort by field (default "created_at", allowed: "name", "created_at", "updated_at").
        sort_order: Sort order (default "asc", allowed: "asc", "desc").
        db: Database session dependency.

    Returns:
        A list of projects sorted and filtered as requested.

    Raises:
        400: If skip/limit invalid, sort_by invalid, or sort_order invalid.
    """
    if skip < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="skip must be >= 0",
        )
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 100",
        )

    valid_sort_fields = {"name", "created_at", "updated_at"}
    if sort_by not in valid_sort_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sort_by must be one of: {', '.join(sorted(valid_sort_fields))}",
        )

    valid_sort_orders = {"asc", "desc"}
    if sort_order not in valid_sort_orders:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sort_order must be one of: {', '.join(sorted(valid_sort_orders))}",
        )

    query = db.query(Project)

    if search:
        query = query.filter(Project.name.ilike(f"%{search}%"))

    sort_column = getattr(Project, sort_by)
    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    projects = query.offset(skip).limit(limit).all()
    return projects


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
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
        400: {"description": "Invalid project ID"},
    },
)
def get_project(project_id: int, db: Session = Depends(get_db)):
    """Retrieve a specific project by ID.

    Fetches a single project from the database using its unique identifier.

    Args:
        project_id: The ID of the project to retrieve (must be > 0).
        db: Database session dependency.

    Returns:
        The requested project.

    Raises:
        400: If project_id is not a positive integer.
        404: If no project with the given ID exists.
    """
    if project_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id must be a positive integer",
        )
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project
