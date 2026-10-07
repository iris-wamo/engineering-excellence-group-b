from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppError,
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
from app.schemas.task import (
    TaskAssignRequest,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
)
from app.workflows.task_workflow import TaskWorkflow


async def _get_project_or_404(db: AsyncSession, project_id: int) -> Project:
    project = await ProjectRepository.get_by_id(db, project_id)
    if project is None:
        raise NotFoundError(
            "Project not found",
            details=[{"field": "project_id", "message": "Project does not exist"}],
        )
    return project


async def _get_user_or_404(db: AsyncSession, user_id: int, field_name: str = "assignee_id") -> User:
    user = await UserRepository.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(
            "User not found",
            details=[{"field": field_name, "message": f"User {user_id} does not exist"}],
        )
    return user


async def _get_task_or_404(db: AsyncSession, task_id: int, *, for_update: bool = False) -> Task:
    if for_update:
        task = await TaskRepository.get_by_id_for_update(db, task_id)
    else:
        task = await TaskRepository.get_by_id(db, task_id)
    if task is None:
        raise NotFoundError(
            "Task not found",
            details=[{"field": "task_id", "message": f"Task {task_id} does not exist"}],
        )
    return task


async def _verify_project_membership(db: AsyncSession, user_id: int, project_id: int) -> None:
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


class TaskService:
    @staticmethod
    async def create_task(db: AsyncSession, data: TaskCreate) -> TaskResponse:
        await _get_project_or_404(db, data.project_id)
        if data.assignee_id is not None:
            await _get_user_or_404(db, data.assignee_id, "assignee_id")

        task = Task(
            title=data.title,
            description=data.description,
            project_id=data.project_id,
            assignee_id=data.assignee_id,
            priority=data.priority,
            due_date=data.due_date,
            status=TaskStatus.todo,
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
    ) -> TaskListResponse:
        tasks, total = await TaskRepository.get_all(
            db,
            page=page,
            page_size=page_size,
            status=status,
            priority=priority,
            project_id=project_id,
            assignee_id=assignee_id,
        )
        return TaskListResponse(
            items=[TaskResponse.model_validate(task) for task in tasks],
            page=page,
            page_size=page_size,
            total=total,
        )

    @staticmethod
    async def get_task(db: AsyncSession, task_id: int) -> TaskResponse:
        task = await _get_task_or_404(db, task_id)
        return TaskResponse.model_validate(task)

    @staticmethod
    async def update_task_status(
        db: AsyncSession,
        task_id: int,
        data: TaskStatusUpdate,
    ) -> TaskResponse:
        # Lock the row so concurrent status changes are validated one after another.
        task = await _get_task_or_404(db, task_id, for_update=True)

        try:
            TaskWorkflow.transition_status(db, task, data.status)
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
        task = await _get_task_or_404(db, task_id, for_update=True)
        try:
            if data.assignee_id is not None:
                await _get_user_or_404(db, data.assignee_id, "assignee_id")
                await _verify_project_membership(db, data.assignee_id, task.project_id)
            if data.assigned_by_id is not None:
                await _get_user_or_404(db, data.assigned_by_id, "assigned_by_id")
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
                TaskWorkflow.transition_status(
                    db, task, data.status, changed_by_id=data.assigned_by_id
                )

            # 2. Assignment history record (only when assignee changed)
            if assignee_changed:
                assignment_history = TaskAssignmentHistory(
                    task_id=task.id,
                    previous_assignee_id=previous_assignee_id,
                    new_assignee_id=data.assignee_id,
                    assigned_by_id=data.assigned_by_id,
                )
                db.add(assignment_history)

            # 3. Activity log record for the assignment itself
            action_name = "TASK_ASSIGNED" if data.assignee_id is not None else "TASK_UNASSIGNED"
            activity_log = ActivityLog(
                actor_id=data.assigned_by_id,
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

            # 5. Notification record (pending outbox for new assignee)
            if data.assignee_id is not None and assignee_changed:
                notification = Notification(
                    recipient_id=data.assignee_id,
                    task_id=task.id,
                    type="TASK_ASSIGNED",
                    status="pending",
                    payload={
                        "task_id": task.id,
                        "task_title": task.title,
                        "assigned_by_id": data.assigned_by_id,
                    },
                )
                db.add(notification)

            # 6. Mid-transaction failure simulation (staged AFTER all writes)
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
