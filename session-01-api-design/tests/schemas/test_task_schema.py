import pytest
from pydantic import ValidationError

from app.schemas.task import TaskCreate


def test_task_create_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title="", project_id=1)


def test_task_create_rejects_title_longer_than_limit() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(title="x" * 101, project_id=1)


def test_task_create_allows_optional_fields() -> None:
    task = TaskCreate(title="Login", project_id=1)

    assert task.description is None
    assert task.assignee_id is None