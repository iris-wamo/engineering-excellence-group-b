import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectCreate


def test_project_create_strips_whitespace_from_name() -> None:
    project = ProjectCreate(name="  My Project  ")

    assert project.name == "My Project"


def test_project_create_rejects_blank_name_after_stripping() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="   ")


def test_project_create_rejects_name_longer_than_database_limit() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="x" * 151)


def test_project_create_rejects_blank_description_after_stripping() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="Project", description="   ")


def test_project_create_allows_missing_description() -> None:
    project = ProjectCreate(name="Project")

    assert project.description is None
