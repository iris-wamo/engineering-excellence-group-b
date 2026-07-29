import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.schemas.project import ProjectCreate
from app.services.project_service import ProjectService


def test_create_project_persists_name_and_description(db_session: Session) -> None:
    payload = ProjectCreate(name="Alpha", description="First project")

    created = ProjectService.create_project(db_session, payload)

    assert created.id is not None
    assert created.name == "Alpha"
    assert created.description == "First project"


def test_get_project_returns_project_by_id(db_session: Session) -> None:
    created = ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))

    found = ProjectService.get_project(db_session, created.id)

    assert found.id == created.id


def test_get_project_raises_not_found_for_missing_project(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        ProjectService.get_project(db_session, 999)


def test_list_projects_supports_pagination(db_session: Session) -> None:
    ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))
    ProjectService.create_project(db_session, ProjectCreate(name="Beta"))
    ProjectService.create_project(db_session, ProjectCreate(name="Gamma"))

    projects, total = ProjectService.list_projects(
        db_session, page=1, page_size=2, search=None, sort_by="name", sort_order="asc"
    )

    assert total == 3
    assert [p.name for p in projects] == ["Alpha", "Beta"]


def test_list_projects_filters_by_search(db_session: Session) -> None:
    ProjectService.create_project(db_session, ProjectCreate(name="Marketing Site"))
    ProjectService.create_project(db_session, ProjectCreate(name="Internal Tool"))

    projects, total = ProjectService.list_projects(
        db_session, page=1, page_size=10, search="marketing", sort_by="name", sort_order="asc"
    )

    assert total == 1
    assert projects[0].name == "Marketing Site"


def test_list_projects_sorts_descending(db_session: Session) -> None:
    ProjectService.create_project(db_session, ProjectCreate(name="Alpha"))
    ProjectService.create_project(db_session, ProjectCreate(name="Beta"))

    projects, _total = ProjectService.list_projects(
        db_session, page=1, page_size=10, search=None, sort_by="name", sort_order="desc"
    )

    assert [p.name for p in projects] == ["Beta", "Alpha"]
