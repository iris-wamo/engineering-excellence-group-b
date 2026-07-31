"""Business logic for task management."""

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import TaskPriority, TaskStatus
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
)


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = TaskRepository.get_project_by_id(db, project_id)
    if project is None:
        raise NotFoundError(
            "Project not found",
            details=[{"field": "project_id", "message": "Project does not exist"}],
        )
    return project


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = TaskRepository.get_user_by_id(db, user_id)
    if user is None:
        raise NotFoundError(
            "Assignee not found",
            details=[{"field": "assignee_id", "message": "User does not exist"}],
        )
    return user


def _get_task_or_404(db: Session, task_id: int) -> Task:
    task = TaskRepository.get_by_id(db, task_id)
    if task is None:
        raise NotFoundError(
            "Task not found",
            details=[{"field": "task_id", "message": "Task does not exist"}],
        )
    return task


class TaskService:
    @staticmethod
    def create_task(db: Session, data: TaskCreate) -> TaskResponse:
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
        task = TaskRepository.create(db, task)
        return TaskResponse.model_validate(task)

    @staticmethod
    def list_tasks(
        db: Session,
        page: int,
        page_size: int,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        project_id: int | None = None,
        assignee_id: int | None = None,
    ) -> TaskListResponse:
        tasks, total = TaskRepository.get_all(
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
    def get_task(db: Session, task_id: int) -> TaskResponse:
        task = _get_task_or_404(db, task_id)
        return TaskResponse.model_validate(task)

    @staticmethod
    def update_task_status(
        db: Session,
        task_id: int,
        data: TaskStatusUpdate,
    ) -> TaskResponse:
        task = _get_task_or_404(db, task_id)
        task.status = data.status
        task = TaskRepository.update(db, task)
        return TaskResponse.model_validate(task)
