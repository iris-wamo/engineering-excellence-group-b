"""Tests for transaction-safe task assignment flow."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, TransactionSimulationError
from app.models.activity_log import ActivityLog
from app.models.enums import TaskStatus
from app.models.notification import Notification
from app.models.task import Task
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskAssignRequest, TaskCreate
from app.schemas.user import UserCreate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.user_service import UserService


@pytest.fixture
async def sample_assignment_data(db_session: AsyncSession):
    """Creates a sample project, task, and multiple users for testing."""
    user_creator = await UserService.create_user(
        db_session, UserCreate(name="Alice Lead", email="alice.lead@example.com")
    )
    user_assignee = await UserService.create_user(
        db_session, UserCreate(name="Bob Dev", email="bob.dev@example.com")
    )
    user_second_assignee = await UserService.create_user(
        db_session, UserCreate(name="Charlie Dev", email="charlie.dev@example.com")
    )
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Core Platform"))
    task = await TaskService.create_task(
        db_session,
        TaskCreate(
            title="Implement Transaction Safety",
            description="Ensure atomic writes on task assignment",
            project_id=project.id,
            assignee_id=None,
        ),
    )
    return {
        "creator": user_creator,
        "assignee": user_assignee,
        "second_assignee": user_second_assignee,
        "project": project,
        "task": task,
    }


async def test_assign_task_success_all_records_created(
    db_session: AsyncSession, sample_assignment_data: dict
) -> None:
    """Tests that initial assignment atomically creates all audit and notification records."""
    data = sample_assignment_data
    task_id = data["task"].id
    assignee_id = data["assignee"].id
    assigned_by_id = data["creator"].id

    updated_task = await TaskService.assign_task(
        db_session,
        task_id=task_id,
        data=TaskAssignRequest(
            assignee_id=assignee_id,
            assigned_by_id=assigned_by_id,
            status=TaskStatus.in_progress,
        ),
    )

    assert updated_task.assignee_id == assignee_id
    assert updated_task.status == TaskStatus.in_progress

    # Verify TaskAssignmentHistory row
    assignment_history_records = (
        await db_session.scalars(
            select(TaskAssignmentHistory).where(TaskAssignmentHistory.task_id == task_id)
        )
    ).all()
    assert len(assignment_history_records) == 1
    assert assignment_history_records[0].previous_assignee_id is None
    assert assignment_history_records[0].new_assignee_id == assignee_id
    assert assignment_history_records[0].assigned_by_id == assigned_by_id

    # Verify TaskStatusHistory row
    status_history_records = (
        await db_session.scalars(
            select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_id)
        )
    ).all()
    assert len(status_history_records) == 1
    assert status_history_records[0].previous_status == TaskStatus.todo
    assert status_history_records[0].new_status == TaskStatus.in_progress
    assert status_history_records[0].changed_by_id == assigned_by_id

    # Verify ActivityLog row
    activity_logs = (
        await db_session.scalars(
            select(ActivityLog).where(
                ActivityLog.entity_type == "task",
                ActivityLog.entity_id == task_id,
            )
        )
    ).all()
    assert len(activity_logs) == 1
    assert activity_logs[0].actor_id == assigned_by_id
    assert activity_logs[0].action == "TASK_ASSIGNED"
    assert activity_logs[0].details["previous_assignee_id"] is None
    assert activity_logs[0].details["new_assignee_id"] == assignee_id

    # Verify Notification row
    notifications = (
        await db_session.scalars(select(Notification).where(Notification.task_id == task_id))
    ).all()
    assert len(notifications) == 1
    assert notifications[0].recipient_id == assignee_id
    assert notifications[0].type == "TASK_ASSIGNED"
    assert notifications[0].status == "pending"


async def test_reassign_task_success(
    db_session: AsyncSession, sample_assignment_data: dict
) -> None:
    """Tests reassigning a task from one user to another."""
    data = sample_assignment_data
    task_id = data["task"].id
    bob_id = data["assignee"].id
    charlie_id = data["second_assignee"].id
    creator_id = data["creator"].id

    # 1. Assign to Bob
    await TaskService.assign_task(
        db_session,
        task_id=task_id,
        data=TaskAssignRequest(assignee_id=bob_id, assigned_by_id=creator_id),
    )

    # 2. Reassign to Charlie
    reassigned_task = await TaskService.assign_task(
        db_session,
        task_id=task_id,
        data=TaskAssignRequest(assignee_id=charlie_id, assigned_by_id=creator_id),
    )

    assert reassigned_task.assignee_id == charlie_id

    # Check assignment history has 2 entries
    histories = (
        await db_session.scalars(
            select(TaskAssignmentHistory)
            .where(TaskAssignmentHistory.task_id == task_id)
            .order_by(TaskAssignmentHistory.id.asc())
        )
    ).all()
    assert len(histories) == 2
    assert histories[1].previous_assignee_id == bob_id
    assert histories[1].new_assignee_id == charlie_id


async def test_assign_task_without_status_transition(
    db_session: AsyncSession, sample_assignment_data: dict
) -> None:
    """Tests assignment when status is not changed (TaskStatusHistory should not be created)."""
    data = sample_assignment_data
    task_id = data["task"].id
    bob_id = data["assignee"].id

    await TaskService.assign_task(
        db_session,
        task_id=task_id,
        data=TaskAssignRequest(assignee_id=bob_id, status=None),
    )

    # Verify status history was NOT created
    status_count = await db_session.scalar(
        select(func.count())
        .select_from(TaskStatusHistory)
        .where(TaskStatusHistory.task_id == task_id)
    )
    assert status_count == 0


async def test_unassign_task_success(
    db_session: AsyncSession, sample_assignment_data: dict
) -> None:
    """Tests unassigning a task (assignee_id set to None)."""
    data = sample_assignment_data
    task_id = data["task"].id
    bob_id = data["assignee"].id
    creator_id = data["creator"].id

    # Assign first
    await TaskService.assign_task(
        db_session,
        task_id=task_id,
        data=TaskAssignRequest(assignee_id=bob_id, assigned_by_id=creator_id),
    )

    # Unassign
    unassigned_task = await TaskService.assign_task(
        db_session,
        task_id=task_id,
        data=TaskAssignRequest(assignee_id=None, assigned_by_id=creator_id),
    )

    assert unassigned_task.assignee_id is None

    histories = (
        await db_session.scalars(
            select(TaskAssignmentHistory)
            .where(TaskAssignmentHistory.task_id == task_id)
            .order_by(TaskAssignmentHistory.id.asc())
        )
    ).all()
    assert len(histories) == 2
    assert histories[1].previous_assignee_id == bob_id
    assert histories[1].new_assignee_id is None


async def test_assign_task_mid_transaction_failure_rolls_back_everything(
    db_session: AsyncSession, sample_assignment_data: dict
) -> None:
    """Tests that mid-flow exception rolls back all partial writes, leaving DB unchanged."""
    data = sample_assignment_data
    task_id = data["task"].id
    bob_id = data["assignee"].id
    creator_id = data["creator"].id
    charlie_id = data["second_assignee"].id

    # First successful assignment to Bob
    await TaskService.assign_task(
        db_session,
        task_id=task_id,
        data=TaskAssignRequest(
            assignee_id=bob_id,
            assigned_by_id=creator_id,
            status=TaskStatus.in_progress,
        ),
    )

    # Capture state BEFORE failed transaction
    task_before = await db_session.get(Task, task_id)
    assert task_before is not None
    assert task_before.assignee_id == bob_id
    assert task_before.status == TaskStatus.in_progress

    hist_before = await db_session.scalar(
        select(func.count())
        .select_from(TaskAssignmentHistory)
        .where(TaskAssignmentHistory.task_id == task_id)
    )
    stat_before = await db_session.scalar(
        select(func.count())
        .select_from(TaskStatusHistory)
        .where(TaskStatusHistory.task_id == task_id)
    )
    act_before = await db_session.scalar(
        select(func.count()).select_from(ActivityLog).where(ActivityLog.entity_id == task_id)
    )
    notif_before = await db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.task_id == task_id)
    )

    # Attempt re-assignment to Charlie with simulated failure
    with pytest.raises(
        TransactionSimulationError,
        match="Simulated failure midway through task assignment",
    ):
        await TaskService.assign_task(
            db_session,
            task_id=task_id,
            data=TaskAssignRequest(
                assignee_id=charlie_id,
                assigned_by_id=creator_id,
                status=TaskStatus.done,
                simulate_failure=True,
            ),
        )

    # Rollback verification: re-query database
    db_session.expire_all()
    task_after = await db_session.get(Task, task_id)
    assert task_after is not None
    assert task_after.assignee_id == bob_id  # Unchanged!
    assert task_after.status == TaskStatus.in_progress  # Unchanged!

    hist_after = await db_session.scalar(
        select(func.count())
        .select_from(TaskAssignmentHistory)
        .where(TaskAssignmentHistory.task_id == task_id)
    )
    stat_after = await db_session.scalar(
        select(func.count())
        .select_from(TaskStatusHistory)
        .where(TaskStatusHistory.task_id == task_id)
    )
    act_after = await db_session.scalar(
        select(func.count()).select_from(ActivityLog).where(ActivityLog.entity_id == task_id)
    )
    notif_after = await db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.task_id == task_id)
    )

    assert hist_after == hist_before
    assert stat_after == stat_before
    assert act_after == act_before
    assert notif_after == notif_before


async def test_assign_task_nonexistent_user_raises_not_found(
    db_session: AsyncSession, sample_assignment_data: dict
) -> None:
    """Tests 404 validation when assignee does not exist."""
    data = sample_assignment_data
    task_id = data["task"].id

    with pytest.raises(NotFoundError):
        await TaskService.assign_task(
            db_session,
            task_id=task_id,
            data=TaskAssignRequest(assignee_id=99999),
        )
