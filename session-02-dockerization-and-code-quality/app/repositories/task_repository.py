from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class TaskRepository:
    @staticmethod
    async def create(db: AsyncSession, task: Task) -> Task:
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: int) -> Task | None:
        return await db.get(Task, task_id)

    @staticmethod
    async def update(db: AsyncSession, task: Task) -> Task:
        await db.commit()
        await db.refresh(task)
        return task

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
    ) -> tuple[list[Task], int]:
        filters = []

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
