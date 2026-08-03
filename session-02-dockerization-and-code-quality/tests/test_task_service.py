import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import TaskStatus
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskStatusUpdate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService


async def test_create_task_success(db_session: AsyncSession) -> None:
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))

    created = await TaskService.create_task(
        db_session, TaskCreate(title="Login", project_id=project.id)
    )

    assert created.id is not None
    assert created.title == "Login"
    assert created.status == TaskStatus.todo


async def test_get_task_raises_404_for_missing_task(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await TaskService.get_task(db_session, 999)


async def test_list_tasks_supports_pagination(db_session: AsyncSession) -> None:
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))
    await TaskService.create_task(db_session, TaskCreate(title="A", project_id=project.id))
    await TaskService.create_task(db_session, TaskCreate(title="B", project_id=project.id))
    await TaskService.create_task(db_session, TaskCreate(title="C", project_id=project.id))

    result = await TaskService.list_tasks(db_session, page=1, page_size=2)

    assert result.total == 3
    assert len(result.items) == 2


async def test_update_task_status(db_session: AsyncSession) -> None:
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))
    created = await TaskService.create_task(
        db_session, TaskCreate(title="Login", project_id=project.id)
    )

    updated = await TaskService.update_task_status(
        db_session, created.id, TaskStatusUpdate(status=TaskStatus.done)
    )

    assert updated.status == TaskStatus.done


async def test_create_task_raises_404_for_missing_project(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await TaskService.create_task(db_session, TaskCreate(title="Login", project_id=999))


async def test_create_task_raises_404_for_missing_assignee(db_session: AsyncSession) -> None:
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))

    with pytest.raises(NotFoundError):
        await TaskService.create_task(
            db_session,
            TaskCreate(title="Login", project_id=project.id, assignee_id=999),
        )


async def test_update_task_status_raises_404_for_missing_task(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await TaskService.update_task_status(
            db_session, 999, TaskStatusUpdate(status=TaskStatus.done)
        )
