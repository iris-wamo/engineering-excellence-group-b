import asyncio
import atexit
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppError,
    ExternalServiceTimeoutError,
    NotFoundError,
    ProjectMembershipRequiredError,
    TransactionSimulationError,
)
from app.models.activity_log import ActivityLog
from app.models.enums import TaskPriority, TaskStatus
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.task import (
    ExternalServiceResult,
    TaskAssignRequest,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
    TaskSummaryResponse,
)
from app.workflows.task_workflow import TaskWorkflow

_EXECUTOR = ThreadPoolExecutor(max_workers=4)
# Prevent leaked worker threads at process exit.
atexit.register(_EXECUTOR.shutdown, wait=False)


async def _simulate_external_call_async(delay: float, timeout: float) -> ExternalServiceResult:
    """Simulate an asynchronous non-blocking external service call with a timeout.

    Uses asyncio.wait_for around asyncio.sleep to yield control back to the event loop.
    Other concurrent tasks run freely during the simulated network wait.
    If delay exceeds timeout, raises ExternalServiceTimeoutError (HTTP 504).
    """
    start = time.perf_counter()
    try:
        await asyncio.wait_for(asyncio.sleep(delay), timeout=timeout)
    except TimeoutError:
        raise ExternalServiceTimeoutError(
            message="External service timed out",
            timeout=timeout,
        ) from None

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return ExternalServiceResult(
        service="workload_service",
        status="healthy",
        latency_ms=latency_ms,
        mode="async",
    )


def _simulate_external_call_blocking(delay: float, timeout: float) -> ExternalServiceResult:
    """Simulate a synchronous blocking external service call.

    Uses time.sleep(delay) on the main thread, blocking the thread running the asyncio event loop.
    This demonstrates event loop starvation and head-of-line blocking under concurrency.

    Timeout behavior simulation:
    In a real synchronous HTTP client (e.g. `requests` or `urllib` with a timeout parameter),
    the underlying socket read/connect blocks the OS thread until either data arrives or the
    socket read timeout expires. If the remote service is unresponsive, the thread remains
    blocked for the full timeout duration before raising a socket timeout exception.
    During that entire window, the thread running the event loop is completely incapacitated.
    Here, when delay > timeout, we simulate this by blocking the thread with time.sleep(timeout)
    and then raising ExternalServiceTimeoutError (HTTP 504).
    """
    start = time.perf_counter()
    if delay > timeout:
        time.sleep(timeout)
        raise ExternalServiceTimeoutError(
            message="External service timed out",
            timeout=timeout,
        )

    time.sleep(delay)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return ExternalServiceResult(
        service="workload_service",
        status="healthy",
        latency_ms=latency_ms,
        mode="blocking",
    )


async def _get_project_or_404(
    db: AsyncSession, project_id: int, workspace_id: int | None = None
) -> Project:
    project = await ProjectRepository.get_by_id(db, project_id, workspace_id=workspace_id)
    if project is None:
        raise NotFoundError(
            "Project not found",
            details=[{"field": "project_id", "message": "Project does not exist"}],
        )
    return project


async def _get_user_or_404(
    db: AsyncSession,
    user_id: int,
    field_name: str = "assignee_id",
    workspace_id: int | None = None,
) -> User:
    user = await UserRepository.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(
            "User not found",
            details=[{"field": field_name, "message": f"User {user_id} does not exist"}],
        )
    if workspace_id is not None:
        is_member = await WorkspaceRepository.is_user_in_workspace(
            db, workspace_id=workspace_id, user_id=user_id
        )
        if not is_member:
            raise NotFoundError(
                "User not found",
                details=[{"field": field_name, "message": f"User {user_id} does not exist"}],
            )
    return user


async def _get_task_or_404(
    db: AsyncSession,
    task_id: int,
    workspace_id: int | None = None,
    *,
    for_update: bool = False,
) -> Task:
    if for_update:
        task = await TaskRepository.get_by_id_for_update(db, task_id, workspace_id=workspace_id)
    else:
        task = await TaskRepository.get_by_id(db, task_id, workspace_id=workspace_id)
    if task is None:
        raise NotFoundError(
            "Task not found",
            details=[{"field": "task_id", "message": f"Task {task_id} does not exist"}],
        )
    return task


async def verify_project_membership(db: AsyncSession, user_id: int, project_id: int) -> None:
    has_members = await db.scalar(
        select(func.count()).select_from(ProjectUser).where(ProjectUser.project_id == project_id)
    )
    if has_members and has_members > 0:
        membership = await db.scalar(
            select(ProjectUser).where(
                ProjectUser.project_id == project_id,
                ProjectUser.user_id == user_id,
            )
        )
        if membership is None:
            raise ProjectMembershipRequiredError(user_id=user_id, project_id=project_id)


_verify_project_membership = verify_project_membership


class TaskService:
    @staticmethod
    async def create_task(
        db: AsyncSession, data: TaskCreate, workspace_id: int = 1
    ) -> TaskResponse:
        project = await _get_project_or_404(db, data.project_id, workspace_id=workspace_id)
        if data.assignee_id is not None:
            await _get_user_or_404(
                db, data.assignee_id, "assignee_id", workspace_id=project.workspace_id
            )
            await _verify_project_membership(db, data.assignee_id, data.project_id)

        task = Task(
            title=data.title,
            description=data.description,
            project_id=data.project_id,
            assignee_id=data.assignee_id,
            priority=data.priority,
            due_date=data.due_date,
            status=TaskStatus.todo,
            workspace_id=project.workspace_id,
        )
        task = await TaskRepository.create(db, task)
        return TaskResponse.model_validate(task)

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        page: int,
        page_size: int,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        project_id: int | None = None,
        assignee_id: int | None = None,
        workspace_id: int | None = None,
    ) -> TaskListResponse:
        tasks, total = await TaskRepository.get_all(
            db,
            page=page,
            page_size=page_size,
            status=status,
            priority=priority,
            project_id=project_id,
            assignee_id=assignee_id,
            workspace_id=workspace_id,
        )
        return TaskListResponse(
            items=[TaskResponse.model_validate(task) for task in tasks],
            page=page,
            page_size=page_size,
            total=total,
        )

    @staticmethod
    async def get_task(
        db: AsyncSession, task_id: int, workspace_id: int | None = None
    ) -> TaskResponse:
        task = await _get_task_or_404(db, task_id, workspace_id=workspace_id)
        return TaskResponse.model_validate(task)

    @staticmethod
    async def update_task_status(
        db: AsyncSession,
        task_id: int,
        data: TaskStatusUpdate,
        workspace_id: int | None = None,
        changed_by_id: int | None = None,
    ) -> TaskResponse:
        # Lock the row so concurrent status changes are validated one after another.
        task = await _get_task_or_404(db, task_id, workspace_id=workspace_id, for_update=True)

        try:
            TaskWorkflow.transition_status(db, task, data.status, changed_by_id=changed_by_id)
        except AppError:
            await db.rollback()  # release the row lock
            raise

        task = await TaskRepository.update(db, task)
        return TaskResponse.model_validate(task)

    @staticmethod
    async def assign_task(
        db: AsyncSession,
        task_id: int,
        data: TaskAssignRequest,
        workspace_id: int | None = None,
        actor_id: int | None = None,
    ) -> TaskResponse:
        """Assign or reassign a task with a single, transaction-safe atomic operation.

        All steps are staged before commit:
        1. Task update (assignee_id, and status if requested)
        2. TaskAssignmentHistory (created only if assignee changes)
        3. Status change via TaskWorkflow (only if status changes): validates the move and
           writes a TaskStatusHistory row plus a STATUS_CHANGED ActivityLog
        4. ActivityLog (TASK_ASSIGNED / TASK_UNASSIGNED audit log of the assignment)
        5. Notification (pending outbox notification for new assignee)

        If any error or simulated failure occurs, the entire transaction rolls back.
        """
        # Lock the row so a concurrent status/assignee change cannot be validated against
        # a stale read.
        task = await _get_task_or_404(db, task_id, workspace_id=workspace_id, for_update=True)
        assigned_by_id = actor_id if actor_id is not None else data.assigned_by_id

        try:
            if data.assignee_id is not None:
                await _get_user_or_404(
                    db, data.assignee_id, "assignee_id", workspace_id=task.workspace_id
                )
                await _verify_project_membership(db, data.assignee_id, task.project_id)
            if assigned_by_id is not None:
                await _get_user_or_404(
                    db, assigned_by_id, "assigned_by_id", workspace_id=task.workspace_id
                )
        except Exception:
            await db.rollback()  # release the row lock
            raise

        try:
            previous_assignee_id = task.assignee_id
            previous_status = task.status
            assignee_changed = data.assignee_id != previous_assignee_id
            status_changed = data.status is not None and data.status != previous_status

            # 1. Update task fields in session
            if assignee_changed:
                task.assignee_id = data.assignee_id
            if status_changed and data.status is not None:
                # Same rules and audit trail as PATCH /status: validates the move and writes
                # the TaskStatusHistory row and a STATUS_CHANGED activity log.
                TaskWorkflow.transition_status(db, task, data.status, changed_by_id=assigned_by_id)

            # 2. Assignment history record (only when assignee changed)
            if assignee_changed:
                assignment_history = TaskAssignmentHistory(
                    task_id=task.id,
                    previous_assignee_id=previous_assignee_id,
                    new_assignee_id=data.assignee_id,
                    assigned_by_id=assigned_by_id,
                )
                db.add(assignment_history)

            # 3. Activity log record for the assignment itself
            action_name = "TASK_ASSIGNED" if data.assignee_id is not None else "TASK_UNASSIGNED"
            activity_log = ActivityLog(
                actor_id=assigned_by_id,
                entity_type="task",
                entity_id=task.id,
                action=action_name,
                details={
                    "previous_assignee_id": previous_assignee_id,
                    "new_assignee_id": data.assignee_id,
                    "assignee_changed": assignee_changed,
                    "previous_status": previous_status.value,
                    "new_status": task.status.value,
                    "status_changed": status_changed,
                },
            )
            db.add(activity_log)

            # 4. Notification record (pending outbox for new assignee)
            if data.assignee_id is not None and assignee_changed:
                notification = Notification(
                    recipient_id=data.assignee_id,
                    task_id=task.id,
                    type="TASK_ASSIGNED",
                    status="pending",
                    payload={
                        "task_id": task.id,
                        "task_title": task.title,
                        "assigned_by_id": assigned_by_id,
                    },
                )
                db.add(notification)

            # 5. Mid-transaction failure simulation (staged AFTER all writes)
            if data.simulate_failure:
                raise TransactionSimulationError(
                    "Simulated failure midway through task assignment transaction"
                )

            await db.commit()
            await db.refresh(task)
            return TaskResponse.model_validate(task)
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def get_task_summary(
        cls,
        db: AsyncSession,
        workspace_id: int,
        external_delay: float = 0.2,
        external_timeout: float = 1.0,
    ) -> TaskSummaryResponse:
        """Fetch task summary asynchronously using non-blocking external I/O.

        The external call is executed before querying the database so that no database
        connection is checked out from the pool while waiting for the simulated external service.
        """
        external_result = await _simulate_external_call_async(
            delay=external_delay, timeout=external_timeout
        )
        metrics = await TaskRepository.get_summary_metrics(db, workspace_id=workspace_id)
        return TaskSummaryResponse(
            workspace_id=workspace_id,
            counts_by_status=metrics["counts_by_status"],
            overdue_count=metrics["overdue_count"],
            assigned_count=metrics["assigned_count"],
            total_count=metrics["total_count"],
            external_service=external_result,
        )

    @classmethod
    async def get_task_summary_blocking(
        cls,
        db: AsyncSession,
        workspace_id: int,
        external_delay: float = 0.2,
        external_timeout: float = 1.0,
    ) -> TaskSummaryResponse:
        """Fetch task summary with the blocking external call offloaded to a thread pool.

        The slow external call is offloaded to a bounded ThreadPoolExecutor so it does not
        block the asyncio event loop thread, while the database query remains async on the loop.

        IMPORTANT:
        Wrapping the executor await with asyncio.wait_for cancels the *await* (the asyncio Future),
        NOT the running OS thread. Synchronous blocking operations (like synchronous HTTP clients
        blocked on socket read/connect) cannot be interrupted from Python. The thread continues
        running in the background until its timeout or completion.

        The external call runs before querying the database, ensuring no database connection
        is checked out from the pool while waiting.
        """
        loop = asyncio.get_running_loop()
        # epsilon gives the blocking helper room to reach its own timeout and raise
        # ExternalServiceTimeoutError first, so callers see the helper's timeout value
        # rather than a generic wait_for cancellation.
        epsilon = 0.05
        try:
            external_result = await asyncio.wait_for(
                loop.run_in_executor(
                    _EXECUTOR,
                    _simulate_external_call_blocking,
                    external_delay,
                    external_timeout,
                ),
                timeout=external_timeout + epsilon,
            )
        # Builtin TimeoutError is raised by asyncio.wait_for in Python >= 3.11 (PEP 654).
        except TimeoutError:
            raise ExternalServiceTimeoutError(
                message="External service timed out",
                timeout=external_timeout,
            ) from None

        metrics = await TaskRepository.get_summary_metrics(db, workspace_id=workspace_id)
        return TaskSummaryResponse(
            workspace_id=workspace_id,
            counts_by_status=metrics["counts_by_status"],
            overdue_count=metrics["overdue_count"],
            assigned_count=metrics["assigned_count"],
            total_count=metrics["total_count"],
            external_service=external_result,
        )
