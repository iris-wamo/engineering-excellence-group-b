from uuid import UUID

from taskflow_shared.logging import set_request_id

from app.events.schemas import TaskEvent, TaskEventType
from app.models.enums import TaskStatus
from app.models.task import Task


def _task(**overrides: object) -> Task:
    fields: dict[str, object] = {
        "id": 42,
        "title": "Write docs",
        "project_id": 3,
        "workspace_id": 1,
        "status": TaskStatus.in_progress,
        "assignee_id": 9,
    }
    fields.update(overrides)
    return Task(**fields)


def test_status_changed_event_carries_who_what_and_when() -> None:
    event = TaskEvent.status_changed(_task(), TaskStatus.todo, actor_id=7)

    assert event.event_type is TaskEventType.status_changed
    assert isinstance(event.event_id, UUID)
    assert event.occurred_at.tzinfo is not None
    assert (event.task_id, event.workspace_id, event.project_id) == (42, 1, 3)
    assert event.actor_id == 7
    assert event.data == {"previous_status": "todo", "new_status": "in_progress"}


def test_assignment_events_distinguish_assigned_and_unassigned() -> None:
    assigned = TaskEvent.assignment_changed(_task(assignee_id=9), None, actor_id=7)
    unassigned = TaskEvent.assignment_changed(_task(assignee_id=None), 9, actor_id=7)

    assert assigned.event_type is TaskEventType.assigned
    assert assigned.data == {"previous_assignee_id": None, "new_assignee_id": 9}
    assert unassigned.event_type is TaskEventType.unassigned
    assert unassigned.data == {"previous_assignee_id": 9, "new_assignee_id": None}


def test_each_event_gets_its_own_id() -> None:
    first = TaskEvent.status_changed(_task(), TaskStatus.todo, actor_id=7)
    second = TaskEvent.status_changed(_task(), TaskStatus.todo, actor_id=7)

    assert first.event_id != second.event_id


def test_event_records_the_request_id_for_log_correlation() -> None:
    set_request_id("req-123")
    try:
        event = TaskEvent.status_changed(_task(), TaskStatus.todo, actor_id=7)
    finally:
        set_request_id(None)

    assert event.request_id == "req-123"


def test_event_survives_a_json_round_trip_unchanged() -> None:
    event = TaskEvent.status_changed(_task(), TaskStatus.todo, actor_id=7)

    assert TaskEvent.model_validate_json(event.model_dump_json()) == event
