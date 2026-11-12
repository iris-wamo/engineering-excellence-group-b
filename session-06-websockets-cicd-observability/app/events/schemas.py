"""The task event payload shared by the publisher and both consumers."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from taskflow_shared.logging import get_request_id

from app.models.enums import TaskStatus
from app.models.task import Task


class TaskEventType(StrEnum):
    status_changed = "task.status_changed"
    assigned = "task.assigned"
    unassigned = "task.unassigned"


class TaskEvent(BaseModel):
    """One thing that happened to a task, serialized as JSON on the wire.

    `event_id` is the identity consumers deduplicate on: a redelivered or republished
    event keeps its id, so processing it again has no effect.
    """

    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: TaskEventType
    schema_version: int = 1
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: int
    workspace_id: int
    project_id: int
    actor_id: int | None = Field(description="User who made the change; null if unknown.")
    request_id: str | None = Field(
        default=None, description="X-Request-ID of the API call, to correlate logs."
    )
    data: dict[str, Any] = Field(
        default_factory=dict, description="Event-specific fields, see the event builders."
    )

    @classmethod
    def status_changed(
        cls, task: Task, previous_status: TaskStatus, actor_id: int | None
    ) -> "TaskEvent":
        return cls._for_task(
            TaskEventType.status_changed,
            task,
            actor_id,
            {"previous_status": previous_status.value, "new_status": task.status.value},
        )

    @classmethod
    def assignment_changed(
        cls, task: Task, previous_assignee_id: int | None, actor_id: int | None
    ) -> "TaskEvent":
        event_type = (
            TaskEventType.assigned if task.assignee_id is not None else TaskEventType.unassigned
        )
        return cls._for_task(
            event_type,
            task,
            actor_id,
            {"previous_assignee_id": previous_assignee_id, "new_assignee_id": task.assignee_id},
        )

    @classmethod
    def _for_task(
        cls,
        event_type: TaskEventType,
        task: Task,
        actor_id: int | None,
        data: dict[str, Any],
    ) -> "TaskEvent":
        return cls(
            event_type=event_type,
            task_id=task.id,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            actor_id=actor_id,
            request_id=get_request_id(),
            data=data,
        )
