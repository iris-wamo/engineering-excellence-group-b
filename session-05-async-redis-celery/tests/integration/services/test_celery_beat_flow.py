"""Integration tests for Celery Beat due-task reminders and deduplication."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole, TaskPriority, TaskStatus
from app.models.notification import Notification
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskAssignRequest, TaskCreate
from app.schemas.user import UserCreate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.tasks import reminder_tasks
from app.tasks.locks import acquire_redis_lock, distributed_lock
from app.tasks.reminder_tasks import (
    _execute_due_task_reminders,
    _process_due_task_reminders,
)
from tests.fixtures.factories import MISSING_ID, DataFactory


@pytest.fixture
async def beat_test_setup(db_session: AsyncSession) -> dict[str, Any]:
    """Create sample users, project, and diverse tasks for testing due-date reminders."""
    lead = await UserService.create_user(
        db_session, UserCreate(name="Beat Lead", email="beat.lead@example.com")
    )
    dev = await UserService.create_user(
        db_session, UserCreate(name="Beat Dev", email="beat.worker@example.com")
    )
    project = await ProjectService.create_project(
        db_session, ProjectCreate(name="Beat Reminders Project")
    )

    db_session.add_all(
        [
            ProjectUser(project_id=project.id, user_id=lead.id, role=ProjectRole.owner),
            ProjectUser(project_id=project.id, user_id=dev.id, role=ProjectRole.member),
        ]
    )
    await db_session.commit()

    # Same calendar day the sweep uses
    today = datetime.now(UTC).date()

    # 1. Due Today, assigned to dev, in progress -> Should be reminded
    task_due_today = await TaskService.create_task(
        db_session,
        TaskCreate(
            title="Deploy Monitoring",
            description="Deploy Flower and Beat",
            project_id=project.id,
            assignee_id=dev.id,
            priority=TaskPriority.high,
            due_date=today,
        ),
    )

    # 2. Due in 30 days -> Should NOT be reminded
    task_due_future = await TaskService.create_task(
        db_session,
        TaskCreate(
            title="Q4 Roadmap",
            description="Future planning",
            project_id=project.id,
            assignee_id=dev.id,
            priority=TaskPriority.medium,
            due_date=today + timedelta(days=30),
        ),
    )

    # 3. Due Today, unassigned -> Should NOT be reminded
    task_unassigned = await TaskService.create_task(
        db_session,
        TaskCreate(
            title="Triage Unassigned",
            description="Unassigned work",
            project_id=project.id,
            assignee_id=None,
            priority=TaskPriority.low,
            due_date=today,
        ),
    )

    return {
        "lead": lead,
        "dev": dev,
        "project": project,
        "task_due_today": task_due_today,
        "task_due_future": task_due_future,
        "task_unassigned": task_unassigned,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_due_task_reminders_filters_and_delivers(
    db_session: AsyncSession,
    beat_test_setup: dict[str, Any],
) -> None:
    """Only incomplete assigned tasks due on or before threshold receive reminders."""
    dev = beat_test_setup["dev"]
    task_due_today = beat_test_setup["task_due_today"]

    result = await _execute_due_task_reminders(db_session, threshold_days=1)

    assert result["status"] == "success"
    assert result["reminders_created"] == 1
    assert task_due_today.id in result["reminded_task_ids"]

    # Verify notification record in DB
    stmt = select(Notification).where(
        Notification.task_id == task_due_today.id,
        Notification.recipient_id == dev.id,
        Notification.type == "TASK_DUE_REMINDER",
    )
    notif = (await db_session.scalars(stmt)).first()
    assert notif is not None
    assert notif.status == "sent"
    assert notif.payload is not None
    assert notif.payload["task_id"] == task_due_today.id
    assert notif.payload["task_title"] == "Deploy Monitoring"
    assert notif.payload["workspace_id"] == 1
    assert notif.payload["project_id"] == beat_test_setup["project"].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_due_task_reminders_idempotent_no_duplicates(
    db_session: AsyncSession,
    beat_test_setup: dict[str, Any],
) -> None:
    """Running the sweep multiple times does not produce duplicate reminder rows."""
    task_due_today = beat_test_setup["task_due_today"]
    dev = beat_test_setup["dev"]

    # First sweep creates the reminder
    res1 = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert res1["reminders_created"] == 1

    # Second sweep skips the reminder
    res2 = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert res2["reminders_created"] == 0
    assert res2["reminders_skipped"] == 1

    # Verify DB has exactly 1 notification
    stmt = select(Notification).where(
        Notification.task_id == task_due_today.id,
        Notification.recipient_id == dev.id,
        Notification.type == "TASK_DUE_REMINDER",
    )
    notifs = (await db_session.scalars(stmt)).all()
    assert len(notifs) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reassigned_task_reminds_new_assignee_within_dedup_window(
    db_session: AsyncSession,
    beat_test_setup: dict[str, Any],
) -> None:
    """Dedup is per (task, recipient): a new assignee is reminded even inside the window."""
    task_due_today = beat_test_setup["task_due_today"]
    dev = beat_test_setup["dev"]
    lead = beat_test_setup["lead"]

    first = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert first["reminders_created"] == 1

    await TaskService.assign_task(
        db_session,
        task_id=task_due_today.id,
        data=TaskAssignRequest(assignee_id=lead.id),
        actor_id=lead.id,
    )

    second = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert second["reminders_created"] == 1
    assert second["reminded_task_ids"] == [task_due_today.id]

    rows = await db_session.execute(
        select(Notification.recipient_id)
        .where(
            Notification.task_id == task_due_today.id,
            Notification.type == "TASK_DUE_REMINDER",
        )
        .order_by(Notification.id)
    )
    assert [recipient_id for (recipient_id,) in rows] == [dev.id, lead.id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_completed_tasks_do_not_receive_reminders(
    db_session: AsyncSession,
    beat_test_setup: dict[str, Any],
) -> None:
    """Tasks marked as done are excluded from reminder sweeps."""
    task_due_today = beat_test_setup["task_due_today"]

    # Mark the task as done
    raw_task = await db_session.get(Task, task_due_today.id)
    assert raw_task is not None
    raw_task.status = TaskStatus.done
    await db_session.commit()

    result = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert result["reminders_created"] == 0
    assert task_due_today.id not in result["reminded_task_ids"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_overlapping_sweep_skips_execution(
    db_session: AsyncSession,
) -> None:
    """When a Redis lock is held by an ongoing run, overlapping execution is skipped."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Lock held

    result = await _process_due_task_reminders(
        threshold_days=1,
        db=db_session,
        redis_client=mock_redis,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "overlapping_run"
    assert result["reminders_created"] == 0


async def _reminded_task_ids(db_session: AsyncSession, project_id: int) -> list[int]:
    rows = await db_session.scalars(
        select(Notification.task_id)
        .join(Task, Task.id == Notification.task_id)
        .where(Task.project_id == project_id, Notification.type == "TASK_DUE_REMINDER")
        .order_by(Notification.task_id)
    )
    return [task_id for task_id in rows if task_id is not None]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_moving_the_due_date_reminds_again_inside_the_dedup_window(
    db_session: AsyncSession,
    beat_test_setup: dict[str, Any],
) -> None:
    """Dedup is per due date: a task moved to a new due date is reminded for that date."""
    task_due_today = beat_test_setup["task_due_today"]
    first = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert first["reminded_task_ids"] == [task_due_today.id]

    raw_task = await db_session.get(Task, task_due_today.id)
    assert raw_task is not None
    raw_task.due_date = datetime.now(UTC).date() + timedelta(days=1)
    await db_session.commit()

    second = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert second["reminded_task_ids"] == [task_due_today.id]

    third = await _execute_due_task_reminders(db_session, threshold_days=1)
    assert third["reminders_created"] == 0
    assert third["reminders_skipped"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_reads_and_commits_in_batches(
    db_session: AsyncSession,
    factory: DataFactory,
) -> None:
    """Every due task is reminded even when they span several batches."""
    project = await factory.project()
    assignee = await factory.member(project)
    today = datetime.now(UTC).date()
    tasks = [
        await factory.task(project, assignee=assignee.id, due_date=today - timedelta(days=n))
        for n in range(5)
    ]

    result = await _execute_due_task_reminders(db_session, batch_size=2, project_id=project.id)

    assert result["tasks_checked"] == 5
    assert result["reminders_created"] == 5
    assert await _reminded_task_ids(db_session, project.id) == sorted(t.id for t in tasks)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_one_failing_reminder_does_not_roll_back_the_others(
    db_session: AsyncSession,
    factory: DataFactory,
) -> None:
    """A reminder that cannot be inserted is skipped; the rest of the sweep is kept."""
    project = await factory.project()
    assignee = await factory.member(project)
    today = datetime.now(UTC).date()
    good_1 = await factory.task(project, assignee=assignee.id, due_date=today)
    bad = await factory.task(project, assignee=assignee.id, due_date=today)
    good_2 = await factory.task(project, assignee=assignee.id, due_date=today)

    build_reminder = reminder_tasks._reminder_for

    def reminder_with_broken_recipient(task: Task, recipient_id: int, day: date) -> Notification:
        notification = build_reminder(task, recipient_id, day)
        if task.id == bad.id:
            notification.recipient_id = MISSING_ID  # violates the user foreign key
        return notification

    with patch.object(reminder_tasks, "_reminder_for", reminder_with_broken_recipient):
        result = await _execute_due_task_reminders(db_session, project_id=project.id)

    assert result["reminders_created"] == 2
    assert result["reminders_failed"] == 1
    assert await _reminded_task_ids(db_session, project.id) == [good_1.id, good_2.id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_project_scoped_sweep_ignores_other_projects(
    db_session: AsyncSession,
    beat_test_setup: dict[str, Any],
    factory: DataFactory,
) -> None:
    project = await factory.project()
    assignee = await factory.member(project)
    scoped = await factory.task(project, assignee=assignee.id, due_date=datetime.now(UTC).date())

    result = await _execute_due_task_reminders(db_session, project_id=project.id)

    assert result["reminded_task_ids"] == [scoped.id]
    assert await _reminded_task_ids(db_session, beat_test_setup["project"].id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lock_is_renewed_while_the_holder_runs(redis_client: Redis) -> None:
    """A run longer than the lock TTL keeps the lock, so the next tick cannot overlap it."""
    key = "taskflow:locks:test-renewal"

    async with distributed_lock(key, timeout_seconds=1, redis_client=redis_client) as token:
        assert token is not None
        await asyncio.sleep(2.5)  # 2.5x the TTL
        assert await redis_client.get(key) == token
        assert await acquire_redis_lock(redis_client, key, timeout_seconds=1) is None

    assert await redis_client.get(key) is None
