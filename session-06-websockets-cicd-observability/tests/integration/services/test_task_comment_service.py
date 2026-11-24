from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.schemas import TaskEventType
from app.models.task_comment import TaskComment
from app.schemas.task_comment import TaskCommentCreate
from app.services import task_comment_service
from app.services.task_comment_service import TaskCommentService
from tests.fixtures.events import stream_events
from tests.fixtures.factories import DEFAULT_WORKSPACE_ID, DataFactory


def _record_commit_order(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    real_commit = AsyncSession.commit

    async def recording_commit(self: AsyncSession) -> None:
        if any(isinstance(obj, TaskComment) for obj in self.new):
            calls.append("commit")
        await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", recording_commit)


async def test_event_is_published_only_after_the_commit(
    db_session: AsyncSession,
    factory: DataFactory,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = await factory.project()
    author = await factory.member(project)
    task = await factory.task(project)

    calls: list[str] = []
    _record_commit_order(monkeypatch, calls)

    real_publish = task_comment_service.publish_task_events

    async def recording_publish(events: Any) -> None:
        calls.append("publish")
        assert [event.data["comment_id"] for event in events] == [
            await db_session.scalar(select(func.max(TaskComment.id)))
        ]
        await real_publish(events)

    monkeypatch.setattr(task_comment_service, "publish_task_events", recording_publish)

    await TaskCommentService.create_comment(
        db_session,
        task.id,
        TaskCommentCreate(content="Committed before anyone hears about it."),
        workspace_id=DEFAULT_WORKSPACE_ID,
        author_id=author.id,
    )

    assert calls == ["commit", "publish"]
    [event] = await stream_events(redis_client)
    assert event.event_type is TaskEventType.comment_added


async def test_a_rolled_back_comment_publishes_nothing(
    db_session: AsyncSession,
    factory: DataFactory,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = await factory.project()
    author = await factory.member(project)
    task = await factory.task(project)

    real_commit = AsyncSession.commit

    async def failing_commit(self: AsyncSession) -> None:
        if any(isinstance(obj, TaskComment) for obj in self.new):
            raise RuntimeError("commit failed")
        await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        await TaskCommentService.create_comment(
            db_session,
            task.id,
            TaskCommentCreate(content="This never lands."),
            workspace_id=DEFAULT_WORKSPACE_ID,
            author_id=author.id,
        )

    monkeypatch.undo()
    assert await stream_events(redis_client) == []
    assert await db_session.scalar(select(func.count()).select_from(TaskComment)) == 0
