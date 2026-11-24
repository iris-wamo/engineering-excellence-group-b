from sqlalchemy.ext.asyncio import AsyncSession

from app.events.publisher import publish_task_events
from app.events.schemas import TaskEvent
from app.models.task_comment import TaskComment
from app.repositories.task_comment_repository import TaskCommentRepository
from app.schemas.task_comment import (
    TaskCommentCreate,
    TaskCommentListResponse,
    TaskCommentResponse,
)

# Reuses the task service's lookup so a missing task answers the same 404 everywhere.
from app.services.task_service import _get_task_or_404


class TaskCommentService:
    @staticmethod
    async def create_comment(
        db: AsyncSession,
        task_id: int,
        data: TaskCommentCreate,
        *,
        workspace_id: int | None = None,
        author_id: int,
    ) -> TaskCommentResponse:
        task = await _get_task_or_404(db, task_id, workspace_id=workspace_id)

        comment = TaskComment(task_id=task.id, user_id=author_id, content=data.content)
        comment = await TaskCommentRepository.create(db, comment)

        await publish_task_events([TaskEvent.comment_added(task, comment)])
        return TaskCommentResponse.model_validate(comment)

    @staticmethod
    async def list_comments(
        db: AsyncSession,
        task_id: int,
        *,
        page: int,
        page_size: int,
        workspace_id: int | None = None,
    ) -> TaskCommentListResponse:
        await _get_task_or_404(db, task_id, workspace_id=workspace_id)

        comments, total = await TaskCommentRepository.get_by_task(
            db, task_id, page=page, page_size=page_size, workspace_id=workspace_id
        )
        return TaskCommentListResponse(
            items=[TaskCommentResponse.model_validate(comment) for comment in comments],
            page=page,
            page_size=page_size,
            total=total,
        )
