"""Integration tests for Celery task assignment notification queuing and processing."""

from typing import Any
from unittest.mock import MagicMock, patch

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
    RecipientNotFoundError,
    TaskNotFoundError,
)
from app.tasks.notification_tasks import (
    _mark_notification_failed,
    _process_assignment_notification,
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
@patch("app.tasks.notification_tasks.send_task_assignment_notification.delay")
async def test_assign_task_triggers_celery_job(
    mock_delay: MagicMock,
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

    # Verify background Celery job was queued with correct parameters
    mock_delay.assert_called_once_with(
        task_id=task.id,
        recipient_id=assignee.id,
        assigned_by_id=creator.id,
    )

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


@pytest.mark.asyncio
@patch("app.tasks.notification_tasks.send_task_assignment_notification.delay")
async def test_assign_task_broker_down_graceful_degradation(
    mock_delay: MagicMock,
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """If the Celery broker is offline, task assignment still commits successfully."""
    mock_delay.side_effect = Exception("Redis connection refused on 6379")

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
    with patch("app.tasks.notification_tasks.send_task_assignment_notification.delay"):
        await TaskService.assign_task(
            db_session,
            task_id=task.id,
            data=TaskAssignRequest(assignee_id=assignee.id),
            actor_id=creator.id,
        )

    # 2. Worker executes notification delivery
    result = await _process_assignment_notification(
        task_id=task.id,
        recipient_id=assignee.id,
        assigned_by_id=creator.id,
        db=db_session,
    )

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

    with patch("app.tasks.notification_tasks.send_task_assignment_notification.delay"):
        await TaskService.assign_task(
            db_session,
            task_id=task.id,
            data=TaskAssignRequest(assignee_id=assignee.id),
            actor_id=creator.id,
        )

    # First run: transitions pending -> sent
    res1 = await _process_assignment_notification(
        task_id=task.id,
        recipient_id=assignee.id,
        assigned_by_id=creator.id,
        db=db_session,
    )
    assert res1["status"] == "sent"
    assert res1["idempotent"] is False

    # Second run (duplicate delivery): skips and returns already_sent
    res2 = await _process_assignment_notification(
        task_id=task.id,
        recipient_id=assignee.id,
        assigned_by_id=creator.id,
        db=db_session,
    )
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
    """Permanent errors are raised for missing entities or mismatched assignee."""
    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    other_user = assignment_setup["other_user"]

    # Missing task
    with pytest.raises(TaskNotFoundError):
        await _process_assignment_notification(
            task_id=999_999,
            recipient_id=assignee.id,
            db=db_session,
        )

    # Missing recipient
    with pytest.raises(RecipientNotFoundError):
        await _process_assignment_notification(
            task_id=task.id,
            recipient_id=999_999,
            db=db_session,
        )

    # Assignee mismatch (task is not currently assigned to this user)
    with pytest.raises(InvalidAssignmentNotificationError):
        await _process_assignment_notification(
            task_id=task.id,
            recipient_id=other_user.id,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_mark_notification_failed(
    db_session: AsyncSession,
    assignment_setup: dict[str, Any],
) -> None:
    """Failed tasks update pending notification status to failed and store the error."""
    task = assignment_setup["task"]
    assignee = assignment_setup["assignee"]
    creator = assignment_setup["creator"]

    with patch("app.tasks.notification_tasks.send_task_assignment_notification.delay"):
        await TaskService.assign_task(
            db_session,
            task_id=task.id,
            data=TaskAssignRequest(assignee_id=assignee.id),
            actor_id=creator.id,
        )

    # Mark failed
    await _mark_notification_failed(
        task_id=task.id,
        recipient_id=assignee.id,
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
