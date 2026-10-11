"""Concurrency test: two status changes on one task must be validated one after the other."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.activity_log import ActivityLog
from app.models.enums import TaskStatus
from app.models.project import Project
from app.models.task import Task
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskStatusUpdate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService, _get_task_or_404
from app.workflows.task_workflow import InvalidStatusTransitionError, TaskWorkflow
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Independent sessions that really commit (unlike the rolled-back db_session fixture)."""
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_concurrent_status_changes_are_serialized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as setup:
        project = await ProjectService.create_project(setup, ProjectCreate(name="Race Project"))
        task = await TaskService.create_task(
            setup, TaskCreate(title="Race Task", project_id=project.id)
        )
        await TaskService.update_task_status(
            setup, task.id, TaskStatusUpdate(status=TaskStatus.in_progress)
        )
        project_id, task_id = project.id, task.id

    try:
        async with session_factory() as session_a, session_factory() as session_b:
            # Request A locks the task and moves it in_progress -> review (not committed yet).
            task_a = await _get_task_or_404(session_a, task_id, for_update=True)
            TaskWorkflow.transition_status(session_a, task_a, TaskStatus.review)

            # Request B tries in_progress -> todo at the same time. It must wait for A's lock.
            request_b = asyncio.create_task(
                TaskService.update_task_status(
                    session_b, task_id, TaskStatusUpdate(status=TaskStatus.todo)
                )
            )
            await asyncio.sleep(0.3)
            assert not request_b.done(), "B should be blocked until A commits"

            await session_a.commit()

            # B now sees `review`, so review -> todo is rejected instead of being applied.
            with pytest.raises(InvalidStatusTransitionError):
                await asyncio.wait_for(request_b, timeout=5)

        async with session_factory() as check:
            final = await check.scalar(select(Task.status).where(Task.id == task_id))
        assert final == TaskStatus.review
    finally:
        async with session_factory() as cleanup:
            await cleanup.execute(
                delete(ActivityLog).where(
                    ActivityLog.entity_type == "task", ActivityLog.entity_id == task_id
                )
            )
            await cleanup.execute(delete(Task).where(Task.id == task_id))
            await cleanup.execute(delete(Project).where(Project.id == project_id))
            await cleanup.commit()
