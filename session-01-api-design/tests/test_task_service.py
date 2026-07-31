import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import TaskStatus
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate, TaskStatusUpdate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService


def test_create_task_success(db_session: Session) -> None:
    project = ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))

    created = TaskService.create_task(
        db_session, TaskCreate(title="Login", project_id=project.id)
    )

    assert created.id is not None
    assert created.title == "Login"
    assert created.status == TaskStatus.todo


def test_get_task_raises_404_for_missing_task(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        TaskService.get_task(db_session, 999)


def test_list_tasks_supports_pagination(db_session: Session) -> None:
    project = ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))
    TaskService.create_task(db_session, TaskCreate(title="A", project_id=project.id))
    TaskService.create_task(db_session, TaskCreate(title="B", project_id=project.id))
    TaskService.create_task(db_session, TaskCreate(title="C", project_id=project.id))

    result = TaskService.list_tasks(db_session, page=1, page_size=2)

    assert result.total == 3
    assert len(result.items) == 2


def test_update_task_status(db_session: Session) -> None:
    project = ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))
    created = TaskService.create_task(
        db_session, TaskCreate(title="Login", project_id=project.id)
    )

    updated = TaskService.update_task_status(
        db_session, created.id, TaskStatusUpdate(status=TaskStatus.done)
    )

    assert updated.status == TaskStatus.done