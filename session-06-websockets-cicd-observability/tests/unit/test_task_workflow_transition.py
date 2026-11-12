"""Unit tests for TaskWorkflow.transition_status: what a move changes and records.

test_task_workflow_rules.py covers which moves are allowed. These tests cover the side
effects of a move, using an in-memory task and a fake session, so no database is needed.
"""

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.enums import TaskStatus
from app.models.task import Task
from app.models.task_status_history import TaskStatusHistory
from app.workflows.task_workflow import InvalidStatusTransitionError, TaskWorkflow


class RecordingSession:
    """Stands in for AsyncSession and only remembers what was added."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        self.added.append(row)

    def of_type(self, model: type) -> list[Any]:
        return [row for row in self.added if isinstance(row, model)]


@pytest.fixture()
def session() -> RecordingSession:
    return RecordingSession()


def _task(status: TaskStatus = TaskStatus.todo) -> Task:
    return Task(id=42, title="Unit task", project_id=1, workspace_id=1, status=status)


def _move(session: RecordingSession, task: Task, new: TaskStatus, actor: int | None = 7) -> None:
    TaskWorkflow.transition_status(cast(AsyncSession, session), task, new, changed_by_id=actor)


def test_valid_move_updates_status(session: RecordingSession) -> None:
    task = _task()

    _move(session, task, TaskStatus.in_progress)

    assert task.status == TaskStatus.in_progress


def test_valid_move_records_history_with_actor(session: RecordingSession) -> None:
    task = _task()

    _move(session, task, TaskStatus.in_progress, actor=7)

    [history] = session.of_type(TaskStatusHistory)
    assert history.task_id == 42
    assert history.previous_status == TaskStatus.todo
    assert history.new_status == TaskStatus.in_progress
    assert history.changed_by_id == 7


def test_valid_move_records_status_changed_activity(session: RecordingSession) -> None:
    task = _task()

    _move(session, task, TaskStatus.in_progress, actor=7)

    [activity] = session.of_type(ActivityLog)
    assert activity.action == "STATUS_CHANGED"
    assert activity.entity_type == "task"
    assert activity.entity_id == 42
    assert activity.actor_id == 7
    assert activity.details == {"previous_status": "todo", "new_status": "in_progress"}


def test_move_without_actor_is_recorded_as_system(session: RecordingSession) -> None:
    task = _task()

    _move(session, task, TaskStatus.in_progress, actor=None)

    [history] = session.of_type(TaskStatusHistory)
    [activity] = session.of_type(ActivityLog)
    assert history.changed_by_id is None
    assert activity.actor_id is None


def test_same_status_changes_and_records_nothing(session: RecordingSession) -> None:
    task = _task(TaskStatus.review)

    _move(session, task, TaskStatus.review)

    assert task.status == TaskStatus.review
    assert session.added == []


def test_rejected_move_leaves_task_and_session_untouched(session: RecordingSession) -> None:
    task = _task(TaskStatus.todo)

    with pytest.raises(InvalidStatusTransitionError):
        _move(session, task, TaskStatus.done)

    assert task.status == TaskStatus.todo
    assert session.added == []


def test_full_lifecycle_records_one_history_row_per_move(session: RecordingSession) -> None:
    task = _task()
    path = [TaskStatus.in_progress, TaskStatus.review, TaskStatus.done]

    for new in path:
        _move(session, task, new)

    moves = [(h.previous_status, h.new_status) for h in session.of_type(TaskStatusHistory)]
    assert moves == [
        (TaskStatus.todo, TaskStatus.in_progress),
        (TaskStatus.in_progress, TaskStatus.review),
        (TaskStatus.review, TaskStatus.done),
    ]
    assert len(session.of_type(ActivityLog)) == 3
    assert task.status == TaskStatus.done


def test_rework_loop_from_review_back_to_in_progress(session: RecordingSession) -> None:
    task = _task(TaskStatus.review)

    _move(session, task, TaskStatus.in_progress)
    _move(session, task, TaskStatus.review)

    assert task.status == TaskStatus.review
    assert len(session.of_type(TaskStatusHistory)) == 2
