"""API routes for task management."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.enums import ImportStatus

from app.auth.dependencies import OptionalCurrentUser
from app.auth.permissions import (
    Permission,
    require_task_assignee,
    require_task_permission,
)
from app.auth.workspace_context import CurrentWorkspaceId
from app.db.session import get_db
from app.models.enums import TaskPriority, TaskStatus
from app.models.user import User
from app.schemas.task import (
    TaskAssignRequest,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
    TaskSummaryResponse,
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
    workspace_id: CurrentWorkspaceId,
    current_user: OptionalCurrentUser,
) -> TaskResponse:
    """Create a new task within the active workspace."""
    return await TaskService.create_task(
        db,
        payload,
        workspace_id=workspace_id,
        actor_id=current_user.id if current_user is not None else None,
    )


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
    workspace_id: CurrentWorkspaceId,
    response: Response,
    current_user: OptionalCurrentUser,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TaskImportResponse:
    """Ingest raw task data into MongoDB first, then attempt normalization into PostgreSQL."""
    res = await TaskImportService.import_raw_task(
        db,
        payload.raw_payload,
        idempotency_key=idempotency_key,
        workspace_id=workspace_id,
        actor_id=current_user.id if current_user is not None else None,
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
    workspace_id: CurrentWorkspaceId,
    current_user: OptionalCurrentUser,
) -> TaskBatchImportResponse:
    """Ingest multiple raw task payloads in batch into MongoDB and normalize to PostgreSQL."""
    total, succeeded, failed, results = await TaskImportService.import_raw_tasks_batch(
        db,
        [item.raw_payload for item in payload.items],
        workspace_id=workspace_id,
        actor_id=current_user.id if current_user is not None else None,
    )
    return TaskBatchImportResponse(
        total=total,
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@router.get("/import/{import_id}", response_model=TaskImportDetailResponse)
async def get_raw_task_import(
    import_id: str,
    workspace_id: CurrentWorkspaceId,
) -> TaskImportDetailResponse:
    """Retrieve raw task import details and current processing status from MongoDB."""
    return await TaskImportService.get_import_by_id(import_id, workspace_id=workspace_id)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: CurrentWorkspaceId,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    project_id: int | None = None,
    assignee_id: int | None = None,
) -> TaskListResponse:
    """List tasks, paginated and optionally filtered within the active workspace."""
    return await TaskService.list_tasks(
        db,
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        project_id=project_id,
        assignee_id=assignee_id,
        workspace_id=workspace_id,
    )


@router.get(
    "/summary",
    response_model=TaskSummaryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_task_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: CurrentWorkspaceId,
    external_delay: float = Query(
        default=0.2,
        ge=0.0,
        le=10.0,
        description="Simulated external service delay in seconds.",
    ),
    external_timeout: float = Query(
        default=1.0,
        gt=0.0,
        le=10.0,
        description="External call timeout threshold in seconds.",
    ),
) -> TaskSummaryResponse:
    """Retrieve task summary asynchronously with non-blocking I/O and timeout enforcement."""
    return await TaskService.get_task_summary(
        db,
        workspace_id=workspace_id,
        external_delay=external_delay,
        external_timeout=external_timeout,
    )


@router.get(
    "/summary/blocking",
    response_model=TaskSummaryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_task_summary_blocking(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: CurrentWorkspaceId,
    external_delay: float = Query(
        default=0.2,
        ge=0.0,
        le=10.0,
        description="Simulated external service delay in seconds.",
    ),
    external_timeout: float = Query(
        default=1.0,
        gt=0.0,
        le=10.0,
        description="External call timeout threshold in seconds.",
    ),
) -> TaskSummaryResponse:
    """Retrieve task summary with synchronous blocking external call offloaded to a thread pool.

    The external call is offloaded to a bounded ThreadPoolExecutor while database access
    remains async on the event loop. Note: allowing external_delay up to 10.0s intentionally
    demonstrates bounded pool saturation when timed-out worker threads keep sleeping.
    """
    # Do not convert this endpoint to a synchronous `def` function or add a sync DB path.
    # Starlette runs synchronous `def` endpoints on its own threadpool; here we only offload
    # the slow external call to a threadpool so the async DB call stays on the event loop.
    return await TaskService.get_task_summary_blocking(
        db,
        workspace_id=workspace_id,
        external_delay=external_delay,
        external_timeout=external_timeout,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: CurrentWorkspaceId,
) -> TaskResponse:
    """Retrieve a task by ID within the active workspace."""
    return await TaskService.get_task(db, task_id, workspace_id=workspace_id)


@router.patch(
    "/{task_id}/status",
    response_model=TaskResponse,
)
async def update_task_status(
    task_id: int,
    payload: TaskStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: CurrentWorkspaceId,
    current_user: Annotated[User, Depends(require_task_assignee)],
) -> TaskResponse:
    """Update the status of an existing task. Only the task's assignee may do this."""
    return await TaskService.update_task_status(
        db,
        task_id,
        payload,
        workspace_id=workspace_id,
        changed_by_id=current_user.id,
    )


@router.post(
    "/{task_id}/assign",
    response_model=TaskResponse,
)
async def assign_task(
    task_id: int,
    payload: TaskAssignRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: CurrentWorkspaceId,
    current_user: Annotated[User, Depends(require_task_permission(Permission.task_assign))],
) -> TaskResponse:
    """Assign or reassign a task. Requires admin, manager, or owner in the task's project."""
    return await TaskService.assign_task(
        db,
        task_id,
        payload,
        workspace_id=workspace_id,
        actor_id=current_user.id,
    )
