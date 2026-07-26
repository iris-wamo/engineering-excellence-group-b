"""Business logic for task management."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import TaskPriority, TaskStatus
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
)


# Helper Functions


def _get_project_or_404(db: Session, project_id: int) -> Project:
    """Return a project or raise NotFoundError."""

    project = db.get(Project, project_id)

    if project is None:
        raise NotFoundError(
            "Project not found",
            details=[
                {
                    "field": "project_id",
                    "message": "Project does not exist",
                }
            ],
        )

    return project


def _get_user_or_404(db: Session, user_id: int) -> User:
    """Return a user or raise NotFoundError."""

    user = db.get(User, user_id)

    if user is None:
        raise NotFoundError(
            "Assignee not found",
            details=[
                {
                    "field": "assignee_id",
                    "message": "User does not exist",
                }
            ],
        )

    return user


def _get_task_or_404(db: Session, task_id: int) -> Task:
    """Return a task or raise NotFoundError."""

    task = db.get(Task, task_id)

    if task is None:
        raise NotFoundError(
            "Task not found",
            details=[
                {
                    "field": "task_id",
                    "message": "Task does not exist",
                }
            ],
        )

    return task



# Services


def create_task(db: Session, data: TaskCreate) -> TaskResponse:
    """Create a new task."""

    _get_project_or_404(db, data.project_id)

    if data.assignee_id is not None:
        _get_user_or_404(db, data.assignee_id)

    task = Task(
        title=data.title.strip(),
        description=data.description,
        project_id=data.project_id,
        assignee_id=data.assignee_id,
        priority=data.priority,
        due_date=data.due_date,
        status=TaskStatus.todo,
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    return TaskResponse.model_validate(task)


def list_tasks(
    db: Session,
    page: int,
    page_size: int,
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    project_id: int | None = None,
    assignee_id: int | None = None,
) -> TaskListResponse:
    """Return a paginated list of tasks."""

    filters = []

    if status:
        filters.append(Task.status == status)

    if priority:
        filters.append(Task.priority == priority)

    if project_id:
        filters.append(Task.project_id == project_id)

    if assignee_id:
        filters.append(Task.assignee_id == assignee_id)

    total = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(*filters)
        )
        or 0
    )

    tasks = db.scalars(
        select(Task)
        .where(*filters)
        .order_by(Task.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return TaskListResponse(
        items=[
            TaskResponse.model_validate(task)
            for task in tasks
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def get_task(db: Session, task_id: int) -> TaskResponse:
    """Return a task by its ID."""

    task = _get_task_or_404(db, task_id)

    return TaskResponse.model_validate(task)


def update_task_status(
    db: Session,
    task_id: int,
    data: TaskStatusUpdate,
) -> TaskResponse:
    """Update the status of an existing task."""

    task = _get_task_or_404(db, task_id)

    task.status = data.status

    db.commit()
    db.refresh(task)

    return TaskResponse.model_validate(task)