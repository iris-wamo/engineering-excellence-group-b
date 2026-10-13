"""Data access layer for the Task model."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class TaskRepository:
    @staticmethod
    async def create(db: AsyncSession, task: Task) -> Task:
        try:
            db.add(task)
            await db.commit()
            await db.refresh(task)
            return task
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_by_id(
        db: AsyncSession, task_id: int, workspace_id: int | None = None
    ) -> Task | None:
        if workspace_id is not None:
            result = await db.execute(
                select(Task).where(Task.id == task_id, Task.workspace_id == workspace_id)
            )
            return result.scalar_one_or_none()
        return await db.get(Task, task_id)

    @staticmethod
    async def get_by_id_for_update(
        db: AsyncSession, task_id: int, workspace_id: int | None = None
    ) -> Task | None:
        """Load a task with a row lock (SELECT ... FOR UPDATE), refreshing any stale copy.

        Concurrent status changes on the same task wait here until the holder commits or
        rolls back, so each one validates against the latest committed status.
        """
        if workspace_id is not None:
            result = await db.execute(
                select(Task)
                .where(Task.id == task_id, Task.workspace_id == workspace_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            return result.scalar_one_or_none()
        return await db.get(Task, task_id, with_for_update=True, populate_existing=True)

    @staticmethod
    async def update(db: AsyncSession, task: Task) -> Task:
        try:
            await db.commit()
            await db.refresh(task)
            return task
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_all(
        db: AsyncSession,
        *,
        page: int,
        page_size: int,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        project_id: int | None,
        assignee_id: int | None,
        workspace_id: int | None = None,
    ) -> tuple[list[Task], int]:
        filters = []

        if workspace_id is not None:
            filters.append(Task.workspace_id == workspace_id)

        if status is not None:
            filters.append(Task.status == status)

        if priority is not None:
            filters.append(Task.priority == priority)

        if project_id is not None:
            filters.append(Task.project_id == project_id)

        if assignee_id is not None:
            filters.append(Task.assignee_id == assignee_id)

        total = await db.scalar(select(func.count()).select_from(Task).where(*filters)) or 0

        tasks = (
            await db.scalars(
                select(Task)
                .where(*filters)
                .order_by(Task.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        return list(tasks), total
