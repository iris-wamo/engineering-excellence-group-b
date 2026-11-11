"""Data access layer for the Task model."""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import case, func, select
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

    @staticmethod
    async def get_summary_metrics(
        db: AsyncSession,
        workspace_id: int,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Aggregate task metrics for a workspace in a single SQL query.

        Counts are computed via SQL CASE conditional aggregation for efficiency:
        - counts_by_status: count for each status in TaskStatus
        - overdue_count: tasks with due_date < current_day and status != done
        - assigned_count: tasks with non-null assignee_id
        - total_count: all tasks in the workspace
        """
        # Due dates are compared against the UTC calendar day, as in the reminder sweep.
        current_day = today or datetime.now(UTC).date()

        stmt = select(
            func.count(case((Task.status == TaskStatus.todo, 1))).label("todo_count"),
            func.count(case((Task.status == TaskStatus.in_progress, 1))).label("in_progress_count"),
            func.count(case((Task.status == TaskStatus.review, 1))).label("review_count"),
            func.count(case((Task.status == TaskStatus.done, 1))).label("done_count"),
            func.count(
                case(
                    (
                        (Task.due_date.is_not(None))
                        & (Task.due_date < current_day)
                        & (Task.status != TaskStatus.done),
                        1,
                    )
                )
            ).label("overdue_count"),
            func.count(case((Task.assignee_id.is_not(None), 1))).label("assigned_count"),
            func.count(Task.id).label("total_count"),
        ).where(Task.workspace_id == workspace_id)

        result = await db.execute(stmt)
        row = result.one()

        return {
            "counts_by_status": {
                TaskStatus.todo.value: row.todo_count or 0,
                TaskStatus.in_progress.value: row.in_progress_count or 0,
                TaskStatus.review.value: row.review_count or 0,
                TaskStatus.done.value: row.done_count or 0,
            },
            "overdue_count": row.overdue_count or 0,
            "assigned_count": row.assigned_count or 0,
            "total_count": row.total_count or 0,
        }
