"""Unit tests for the TaskWorkflow transition rules (pure logic, no HTTP or DB)."""

import itertools

import pytest

from app.models.enums import TaskStatus
from app.workflows.task_workflow import InvalidStatusTransitionError, TaskWorkflow

ALLOWED = {
    (TaskStatus.todo, TaskStatus.in_progress),
    (TaskStatus.in_progress, TaskStatus.todo),
    (TaskStatus.in_progress, TaskStatus.review),
    (TaskStatus.review, TaskStatus.in_progress),
    (TaskStatus.review, TaskStatus.done),
    (TaskStatus.done, TaskStatus.review),
}

# Every ordered pair of different statuses (4 x 3 = 12), split into allowed and rejected.
ALL_MOVES = list(itertools.permutations(TaskStatus, 2))
REJECTED = [move for move in ALL_MOVES if move not in ALLOWED]


@pytest.mark.parametrize(("current", "new"), sorted(ALLOWED))
def test_allowed_transition_passes(current: TaskStatus, new: TaskStatus) -> None:
    TaskWorkflow.validate_transition(current, new)


@pytest.mark.parametrize(("current", "new"), REJECTED)
def test_disallowed_transition_raises(current: TaskStatus, new: TaskStatus) -> None:
    with pytest.raises(InvalidStatusTransitionError) as exc_info:
        TaskWorkflow.validate_transition(current, new)

    assert exc_info.value.code == "INVALID_STATUS_TRANSITION"
    assert exc_info.value.status_code == 400
    assert exc_info.value.details[0]["field"] == "status"


def test_rule_table_matches_expected_moves() -> None:
    """Guards against the rules changing without these tests being updated."""
    actual = {(cur, new) for cur, nxt in TaskWorkflow.ALLOWED_TRANSITIONS.items() for new in nxt}
    assert actual == ALLOWED
    assert len(REJECTED) == 6
