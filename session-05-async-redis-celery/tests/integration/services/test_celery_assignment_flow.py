"""Integration tests for Celery task assignment notification queuing and processing."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole
from app.models.notification import Notification
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskAssignRequest, TaskCreate
from app.schemas.user import UserCreate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.tasks.exceptions import (
    InvalidAssignmentNotificationError,
    NotificationNotFoundError,
)
from app.tasks.notification_tasks import (
    _mark_notification_failed,
    _process_assignment_notification,
    _process_stale_pending_notifications,
    requeue_stale_assignment_notifications,
)

APPLY_ASYNC = "app.tasks.notification_tasks.send_task_assignment_notification.apply_async"


async def _pending_notification_id(db: AsyncSession, task_id: int, recipient_id: int) -> int:
    notification_id = await db.scalar(
        select(Notification.id).where(
            Notification.task_id == task_id,
            Notification.recipient_id == recipient_id,
            Notification.status == "pending",
        )
    )
    assert notification_id is not None
    return notification_id


async def _assign(db: AsyncSession, task_id: int, assignee_id: int, actor_id: int) -> None:
    with patch(APPLY_ASYNC):
        await TaskService.assign_task(
            db, task_id=task_id, data=TaskAssignRequest(assignee_id=assignee_id), actor_id=actor_id
        )


@pytest.fixture
async def assignment_setup(db_session: AsyncSession) -> dict[str, Any]:
    """Create a sample project, task, and users for testing assignment notifications."""
    creator = await UserService.create_user(
        db_session, UserCreate(name="Lead Owner", email="lead.owner@example.com")
    )
    assignee = await UserService.create_user(
        db_session, UserCreate(name="Dev Worker", email="dev.worker@example.com")
    )
    other_user = await UserService.create_user(
        db_session, UserCreate(name="Other Dev", email="other.dev@example.com")
    )
    project = await ProjectService.create_project(
        db_session, ProjectCreate(name="Notification Platform")
    )

    db_session.add_all(
        [
            ProjectUser(project_id=project.id, user_id=creator.id, role=ProjectRole.owner),
            ProjectUser(project_id=project.id, user_id=assignee.id, role=ProjectRole.member),
            ProjectUser(project_id=project.id, user_id=other_user.id, role=ProjectRole.member),
        ]
    )
    await db_session.commit()

    task = await TaskService.create_task(
        db_session,
        TaskCreate(
            title="Implement Celery Notifications",
            description="Add retryable background task notification",
            project_id=project.id,
            assignee_id=None,
        ),
    )
    return {
        "creator": creator,
        "assignee": assignee,
        "other_user": other_user,
        "project": project,
        "task": task,
    }


@pytest.mark.asyncio
@patch("app.tasks.notification_tasks.send_task_assignment_notification.apply_async")
async def test_assign_task_triggers_celery_job(
    mock_apply_async: MagicMock,
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """Assigning a task commits the transaction and queues send_task_assignment_notification."""
    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    creator = assignment_setup["creator"]

    updated = await TaskService.assign_task(
        db_session,
        task_id=task.id,
        data=TaskAssignRequest(assignee_id=assignee.id),
        actor_id=creator.id,
    )
    assert updated.assignee_id == assignee.id

    # Verify pending notification row was recorded in DB
    notifications = (
        await db_session.scalars(
            select(Notification).where(
                Notification.task_id == task.id,
                Notification.recipient_id == assignee.id,
            )
        )
    ).all()
    assert len(notifications) == 1
    assert notifications[0].status == "pending"
    assert notifications[0].type == "TASK_ASSIGNED"

    # Verify background Celery job was queued for that row, without publish retries
    mock_apply_async.assert_called_once_with(
        kwargs={"notification_id": notifications[0].id}, retry=False
    )


@pytest.mark.asyncio
@patch("app.tasks.notification_tasks.send_task_assignment_notification.apply_async")
async def test_assign_task_broker_down_graceful_degradation(
    mock_apply_async: MagicMock,
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """If the Celery broker is offline, task assignment still commits successfully."""
    mock_apply_async.side_effect = Exception("Redis connection refused on 6379")

    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    creator = assignment_setup["creator"]

    updated = await TaskService.assign_task(
        db_session,
        task_id=task.id,
        data=TaskAssignRequest(assignee_id=assignee.id),
        actor_id=creator.id,
    )
    assert updated.assignee_id == assignee.id

    # Assignment was committed despite broker error
    refreshed_task = await db_session.get(Task, task.id)
    assert refreshed_task is not None
    assert refreshed_task.assignee_id == assignee.id

    # The outbox row stays pending for the sweep to re-publish
    notification = await db_session.scalar(
        select(Notification).where(Notification.task_id == task.id)
    )
    assert notification is not None
    assert notification.status == "pending"


@pytest.mark.asyncio
async def test_process_assignment_notification_success(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """Worker processing transitions pending notification to sent and updates payload."""
    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    creator = assignment_setup["creator"]

    # 1. Assign task (creates pending notification)
    with patch("app.tasks.notification_tasks.send_task_assignment_notification.apply_async"):
        await TaskService.assign_task(
            db_session,
            task_id=task.id,
            data=TaskAssignRequest(assignee_id=assignee.id),
            actor_id=creator.id,
        )

    # 2. Worker executes notification delivery
    notification_id = await _pending_notification_id(db_session, task.id, assignee.id)
    result = await _process_assignment_notification(notification_id, db=db_session)

    assert result["status"] == "sent"
    assert result["idempotent"] is False

    # Verify notification in database
    notifications = (
        await db_session.scalars(
            select(Notification).where(
                Notification.task_id == task.id,
                Notification.recipient_id == assignee.id,
            )
        )
    ).all()
    assert len(notifications) == 1
    assert notifications[0].status == "sent"
    assert notifications[0].payload is not None
    assert notifications[0].payload.get("dispatched") is True
    assert notifications[0].payload.get("task_title") == task.title


@pytest.mark.asyncio
async def test_process_assignment_notification_idempotent_duplicate(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """Running the job a second time returns already_sent without creating duplicate rows."""
    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    creator = assignment_setup["creator"]

    with patch("app.tasks.notification_tasks.send_task_assignment_notification.apply_async"):
        await TaskService.assign_task(
            db_session,
            task_id=task.id,
            data=TaskAssignRequest(assignee_id=assignee.id),
            actor_id=creator.id,
        )

    # First run: transitions pending -> sent
    notification_id = await _pending_notification_id(db_session, task.id, assignee.id)
    res1 = await _process_assignment_notification(notification_id, db=db_session)
    assert res1["status"] == "sent"
    assert res1["idempotent"] is False

    # Second run (duplicate delivery): skips and returns already_sent
    res2 = await _process_assignment_notification(notification_id, db=db_session)
    assert res2["status"] == "already_sent"
    assert res2["idempotent"] is True

    # Confirm only one notification row exists in DB
    all_notifications = (
        await db_session.scalars(
            select(Notification).where(
                Notification.task_id == task.id,
                Notification.recipient_id == assignee.id,
            )
        )
    ).all()
    assert len(all_notifications) == 1


@pytest.mark.asyncio
async def test_process_assignment_notification_entity_validations(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """Permanent errors are raised for a missing row or a mismatched assignee."""
    task = assignment_setup["task"]
    other_user = assignment_setup["other_user"]

    # Missing notification row
    with pytest.raises(NotificationNotFoundError):
        await _process_assignment_notification(999_999, db=db_session)

    # Assignee mismatch (task is not currently assigned to this user)
    stale = Notification(
        recipient_id=other_user.id, task_id=task.id, type="TASK_ASSIGNED", status="pending"
    )
    db_session.add(stale)
    await db_session.flush()
    with pytest.raises(InvalidAssignmentNotificationError):
        await _process_assignment_notification(stale.id, db=db_session)


@pytest.mark.asyncio
async def test_mark_notification_failed(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """Failed tasks update pending notification status to failed and store the error."""
    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    creator = assignment_setup["creator"]

    with patch("app.tasks.notification_tasks.send_task_assignment_notification.apply_async"):
        await TaskService.assign_task(
            db_session,
            task_id=task.id,
            data=TaskAssignRequest(assignee_id=assignee.id),
            actor_id=creator.id,
        )

    # Mark failed
    notification_id = await _pending_notification_id(db_session, task.id, assignee.id)
    await _mark_notification_failed(
        notification_id,
        error_message="Exceeded max retries: Database timeout",
        db=db_session,
    )

    notifications = (
        await db_session.scalars(
            select(Notification).where(
                Notification.task_id == task.id,
                Notification.recipient_id == assignee.id,
            )
        )
    ).all()
    assert len(notifications) == 1
    assert notifications[0].status == "failed"
    assert notifications[0].payload is not None
    assert "Database timeout" in notifications[0].payload.get("error", "")


@pytest.mark.asyncio
async def test_reassignment_back_to_earlier_assignee_delivers_new_notification(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """A -> B -> A: the second assignment to A is delivered, not skipped as already_sent."""
    task = assignment_setup["task"]
    user_a = assignment_setup["assignee"]
    user_b = assignment_setup["other_user"]
    creator = assignment_setup["creator"]

    await _assign(db_session, task.id, user_a.id, creator.id)
    first_a = await _pending_notification_id(db_session, task.id, user_a.id)
    assert (await _process_assignment_notification(first_a, db=db_session))["status"] == "sent"

    await _assign(db_session, task.id, user_b.id, creator.id)
    to_b = await _pending_notification_id(db_session, task.id, user_b.id)
    assert (await _process_assignment_notification(to_b, db=db_session))["status"] == "sent"

    await _assign(db_session, task.id, user_a.id, creator.id)
    second_a = await _pending_notification_id(db_session, task.id, user_a.id)
    result = await _process_assignment_notification(second_a, db=db_session)

    assert result == {
        "status": "sent",
        "notification_id": second_a,
        "task_id": task.id,
        "recipient_id": user_a.id,
        "idempotent": False,
    }
    statuses = (
        await db_session.execute(
            select(Notification.id, Notification.status)
            .where(Notification.task_id == task.id, Notification.recipient_id == user_a.id)
            .order_by(Notification.id)
        )
    ).all()
    assert [tuple(row) for row in statuses] == [(first_a, "sent"), (second_a, "sent")]


@pytest.mark.asyncio
async def test_mark_notification_failed_only_touches_that_row(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """Failing one row leaves other rows for the same task and recipient alone."""
    task = assignment_setup["task"]
    user_a = assignment_setup["assignee"]
    user_b = assignment_setup["other_user"]
    creator = assignment_setup["creator"]

    await _assign(db_session, task.id, user_a.id, creator.id)
    first_a = await _pending_notification_id(db_session, task.id, user_a.id)
    await _assign(db_session, task.id, user_b.id, creator.id)
    await _assign(db_session, task.id, user_a.id, creator.id)
    second_a = (
        await db_session.scalars(
            select(Notification.id)
            .where(Notification.task_id == task.id, Notification.recipient_id == user_a.id)
            .order_by(Notification.id.desc())
        )
    ).first()
    assert second_a is not None and second_a != first_a

    await _mark_notification_failed(second_a, "boom", db=db_session)

    first = await db_session.get(Notification, first_a)
    second = await db_session.get(Notification, second_a)
    assert first is not None and first.status == "pending"
    assert second is not None and second.status == "failed"

    # A row that was already delivered is never flipped to failed
    first.status = "sent"
    await db_session.flush()
    await _mark_notification_failed(first_a, "late failure", db=db_session)
    await db_session.refresh(first)
    assert first.status == "sent"


@pytest.mark.asyncio
async def test_stale_pending_sweep_finds_only_old_pending_assignments(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """The outbox sweep selects pending TASK_ASSIGNED rows older than the cutoff only."""
    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    old = datetime.now(UTC) - timedelta(minutes=30)

    def row(status: str, created_at: datetime | None = None, type_: str = "TASK_ASSIGNED") -> Any:
        n = Notification(recipient_id=assignee.id, task_id=task.id, type=type_, status=status)
        if created_at is not None:
            n.created_at = created_at
        return n

    stale = row("pending", old)
    fresh = row("pending")
    sent = row("sent", old)
    failed = row("failed", old)
    other_type = row("pending", old, type_="TASK_DUE_REMINDER")
    db_session.add_all([stale, fresh, sent, failed, other_type])
    await db_session.flush()

    ids = await _process_stale_pending_notifications(older_than_minutes=5, limit=100, db=db_session)

    assert ids == [stale.id]


def test_requeue_stale_assignment_notifications_publishes_each_row() -> None:
    """The Beat task re-publishes every stale row it finds, keyed by notification id."""
    with (
        patch("app.tasks.notification_tasks.run_async", side_effect=_close_and_return([7, 9])),
        patch(APPLY_ASYNC) as mock_apply_async,
    ):
        result = requeue_stale_assignment_notifications()

    assert result == {"requeued": 2, "notification_ids": [7, 9]}
    assert mock_apply_async.call_args_list == [
        call(kwargs={"notification_id": 7}, retry=False),
        call(kwargs={"notification_id": 9}, retry=False),
    ]


def _close_and_return(value: Any) -> Any:
    def side_effect(coro: Any) -> Any:
        coro.close()
        return value

    return side_effect
