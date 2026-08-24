"""Business logic for task management."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import TaskPriority, TaskStatus
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
)


async def _get_project_or_404(db: AsyncSession, project_id: int) -> Project:
    project = await ProjectRepository.get_by_id(db, project_id)
    if project is None:
        raise NotFoundError(
            "Project not found",
            details=[{"field": "project_id", "message": "Project does not exist"}],
        )
    return project


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await UserRepository.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(
            "Assignee not found",
            details=[{"field": "assignee_id", "message": "User does not exist"}],
        )
    return user


async def _get_task_or_404(db: AsyncSession, task_id: int) -> Task:
    task = await TaskRepository.get_by_id(db, task_id)
    if task is None:
        raise NotFoundError(
            "Task not found",
            details=[{"field": "task_id", "message": "Task does not exist"}],
        )
    return task


class TaskService:
    @staticmethod
    async def create_task(db: AsyncSession, data: TaskCreate) -> TaskResponse:
        await _get_project_or_404(db, data.project_id)
        if data.assignee_id is not None:
            await _get_user_or_404(db, data.assignee_id)

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
        task = await _get_task_or_404(db, task_id)
        task.status = data.status
        task = await TaskRepository.update(db, task)
        return TaskResponse.model_validate(task)
