"""Helpers for task event tests: building events and reading back what was published."""

from typing import cast

from redis.asyncio import Redis

from app.core.config import settings
from app.events.consumers import StreamEntry
from app.events.schemas import TaskEvent, TaskEventType


def make_event(
    event_type: TaskEventType = TaskEventType.status_changed, task_id: int = 1
) -> TaskEvent:
    """A task event with made-up ids, for tests that do not need a real task."""
    data: dict[str, object] = (
        {"previous_status": "todo", "new_status": "in_progress"}
        if event_type is TaskEventType.status_changed
        else {"previous_assignee_id": None, "new_assignee_id": 5}
    )
    return TaskEvent(
        event_type=event_type, task_id=task_id, workspace_id=1, project_id=1, actor_id=2, data=data
    )


async def stream_entries(redis: Redis, stream: str | None = None) -> list[StreamEntry]:
    """Every (entry id, fields) in a stream, oldest first. Defaults to the task events stream."""
    return cast(list[StreamEntry], await redis.xrange(stream or settings.task_events_stream))


async def stream_events(redis: Redis) -> list[TaskEvent]:
    """Every event currently in the task events stream, oldest first."""
    return [
        TaskEvent.model_validate_json(fields["payload"])
        for _, fields in await stream_entries(redis)
    ]
