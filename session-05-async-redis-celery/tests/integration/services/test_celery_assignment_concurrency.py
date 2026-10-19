"""Concurrency test: delivery racing a reassignment must not notify the replaced assignee."""

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.notification import Notification
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.task import TaskCreate
from app.services.task_service import (
    TaskService,
    _cancel_pending_assignment_notifications,
    _get_task_or_404,
)
from app.tasks.notification_tasks import _execute_assignment_notification
from tests.fixtures.factories import DataFactory


@pytest.fixture
async def session_factory(
    test_database: str,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Independent sessions that really commit (unlike the rolled-back db_session fixture)."""
    engine = create_async_engine(test_database)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_delivery_waits_for_in_flight_reassignment_and_skips_cancelled_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as setup:
        factory = DataFactory(setup)
        workspace = await factory.workspace(slug=f"race-{uuid4().hex[:8]}")
        project = await factory.project(workspace=workspace)
        old_assignee = await factory.member(project, email=f"a-{uuid4().hex}@example.com")
        new_assignee = await factory.member(project, email=f"b-{uuid4().hex}@example.com")
        task = await TaskService.create_task(
            setup,
            TaskCreate(title="Race Task", project_id=project.id, assignee_id=old_assignee.id),
            workspace_id=workspace.id,
        )
        notification_id = await setup.scalar(
            select(Notification.id).where(Notification.task_id == task.id)
        )
        assert notification_id is not None

    try:
        async with session_factory() as reassign, session_factory() as worker:
            # The reassignment locks the task and moves it to B (not committed yet), as
            # TaskService.assign_task does before cancelling A's pending notification.
            locked = await _get_task_or_404(
                reassign, task.id, workspace_id=workspace.id, for_update=True
            )
            locked.assignee_id = new_assignee.id
            await reassign.flush()

            # Delivery of A's notification starts meanwhile. It must wait for the task lock.
            delivery = asyncio.create_task(
                _execute_assignment_notification(worker, notification_id)
            )
            await asyncio.sleep(0.3)
            assert not delivery.done(), "delivery should wait for the reassignment to commit"

            await _cancel_pending_assignment_notifications(reassign, task.id, old_assignee.id)
            await reassign.commit()

            result = await asyncio.wait_for(delivery, timeout=5)
            await worker.commit()

        assert result["status"] == "skipped"
        async with session_factory() as check:
            status = await check.scalar(
                select(Notification.status).where(Notification.id == notification_id)
            )
        assert status == "cancelled"
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await cleanup.execute(
                delete(User).where(User.id.in_([old_assignee.id, new_assignee.id]))
            )
            await cleanup.commit()
