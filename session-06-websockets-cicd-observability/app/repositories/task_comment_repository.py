from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.task_comment import TaskComment


class TaskCommentRepository:
    @staticmethod
    async def create(db: AsyncSession, comment: TaskComment) -> TaskComment:
        try:
            db.add(comment)
            await db.commit()
            await db.refresh(comment)
            return comment
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_by_task(
        db: AsyncSession,
        task_id: int,
        *,
        page: int,
        page_size: int,
        workspace_id: int | None = None,
    ) -> tuple[list[TaskComment], int]:
        filters = [TaskComment.task_id == task_id]
        if workspace_id is not None:
            filters.append(Task.workspace_id == workspace_id)

        total = (
            await db.scalar(
                select(func.count())
                .select_from(TaskComment)
                .join(Task, TaskComment.task_id == Task.id)
                .where(*filters)
            )
            or 0
        )

        comments = (
            await db.scalars(
                select(TaskComment)
                .join(Task, TaskComment.task_id == Task.id)
                .where(*filters)
                .order_by(TaskComment.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        return list(comments), total
