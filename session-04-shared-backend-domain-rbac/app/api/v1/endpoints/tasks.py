"""API routes for task management."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.enums import ImportStatus

from app.db.session import get_db
from app.models.enums import TaskPriority, TaskStatus
from app.schemas.task import (
    TaskAssignRequest,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
)
from app.schemas.task_import import (
    TaskBatchImportRequest,
    TaskBatchImportResponse,
    TaskImportDetailResponse,
    TaskImportResponse,
    TaskRawImportRequest,
)
from app.services.task_import_service import TaskImportService
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    """Create a new task."""
    return await TaskService.create_task(db, payload)


@router.post(
    "/import",
    response_model=TaskImportResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "Raw payload stored in MongoDB and normalized into PostgreSQL.",
            "model": TaskImportResponse,
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Raw payload stored in MongoDB, but normalization failed.",
            "model": TaskImportResponse,
        },
    },
)
async def import_raw_task(
    payload: TaskRawImportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TaskImportResponse:
    """Ingest raw task data into MongoDB first, then attempt normalization into PostgreSQL."""
    res = await TaskImportService.import_raw_task(
        db, payload.raw_payload, idempotency_key=idempotency_key
    )
    if res.status == ImportStatus.FAILED:
        response.status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return res


@router.post(
    "/import/batch",
    response_model=TaskBatchImportResponse,
    status_code=status.HTTP_200_OK,
)
async def import_raw_tasks_batch(
    payload: TaskBatchImportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskBatchImportResponse:
    """Ingest multiple raw task payloads in batch into MongoDB and normalize to PostgreSQL."""
    total, succeeded, failed, results = await TaskImportService.import_raw_tasks_batch(
        db, [item.raw_payload for item in payload.items]
    )
    return TaskBatchImportResponse(
        total=total,
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@router.get("/import/{import_id}", response_model=TaskImportDetailResponse)
async def get_raw_task_import(import_id: str) -> TaskImportDetailResponse:
    """Retrieve raw task import details and current processing status from MongoDB."""
    return await TaskImportService.get_import_by_id(import_id)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    project_id: int | None = None,
    assignee_id: int | None = None,
) -> TaskListResponse:
    """List tasks, paginated and optionally filtered."""
    return await TaskService.list_tasks(
        db,
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        project_id=project_id,
        assignee_id=assignee_id,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: Annotated[AsyncSession, Depends(get_db)]) -> TaskResponse:
    """Retrieve a task by ID."""
    return await TaskService.get_task(db, task_id)


@router.patch("/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: int,
    payload: TaskStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    """Update the status of an existing task."""
    return await TaskService.update_task_status(db, task_id, payload)


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: int,
    payload: TaskAssignRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    """Assign or reassign a task in a transaction-safe manner."""
    return await TaskService.assign_task(db, task_id, payload)
