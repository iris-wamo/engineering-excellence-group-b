from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import TaskPriority, TaskStatus
from app.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
)
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new task."""
    return TaskService.create_task(db, payload)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    project_id: int | None = None,
    assignee_id: int | None = None,
):
    """List tasks, paginated and optionally filtered."""
    return TaskService.list_tasks(
        db,
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        project_id=project_id,
        assignee_id=assignee_id,
    )


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Annotated[Session, Depends(get_db)]):
    """Retrieve a task by ID."""
    return TaskService.get_task(db, task_id)


@router.patch("/{task_id}/status", response_model=TaskResponse)
def update_task_status(
    task_id: int,
    payload: TaskStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    """Update the status of an existing task."""
    return TaskService.update_task_status(db, task_id, payload)
