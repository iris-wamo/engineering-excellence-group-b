"""Integration tests for Celery Beat due-task reminders and deduplication."""

from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole, TaskPriority, TaskStatus
from app.models.notification import Notification
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.schemas.user import UserCreate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.tasks.reminder_tasks import (
    _execute_due_task_reminders,
    _process_due_task_reminders,
)


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

    today = date.today()

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
