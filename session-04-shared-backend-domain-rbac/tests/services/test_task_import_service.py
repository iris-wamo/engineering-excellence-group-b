"""Integration and unit tests for TaskImportService."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.mongo import get_raw_task_imports_collection
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.task_import_service import TaskImportService


@pytest.fixture(autouse=True)
def clean_mongo_imports() -> None:
    """Ensure clean raw_task_imports collection before each test."""
    col = get_raw_task_imports_collection()
    col.delete_many({})


async def _create_test_project(
    db: AsyncSession, name: str = "Import Project", slug: str = "import-project"
) -> Project:
    proj = Project(name=name, slug=slug, description="Project for import testing")
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def _create_test_user(db: AsyncSession, email: str = "importer@example.com") -> User:
    user = User(name="Importer", email=email)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_import_raw_task_success(db_session: AsyncSession) -> None:
    project = await _create_test_project(db_session)
    raw = {
        "summary": "Implement OAuth2 Flow",
        "description": "Imported from external Jira sprint",
        "project_id": project.id,
        "priority": "high",
        "status": "in_progress",
        "jira_key": "SEC-402",
        "external_tags": ["security", "auth"],
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "SUCCESS"
    assert result.postgres_task_id is not None
    assert result.error_details is None

    # Verify task in PostgreSQL
    task = await db_session.get(Task, result.postgres_task_id)
    assert task is not None
    assert task.title == "Implement OAuth2 Flow"
    assert task.description == "Imported from external Jira sprint"
    assert task.priority.value == "high"
    assert task.status.value == "in_progress"
    assert task.mongo_import_id == result.import_id

    # Verify document in MongoDB
    detail = TaskImportService.get_import_by_id(result.import_id)
    assert detail.status == "SUCCESS"
    assert detail.postgres_task_id == task.id
    assert detail.raw_payload["jira_key"] == "SEC-402"
    assert detail.raw_payload["external_tags"] == ["security", "auth"]


async def test_import_raw_task_missing_title_fails(db_session: AsyncSession) -> None:
    project = await _create_test_project(db_session)
    raw = {
        "project_id": project.id,
        "priority": "low",
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "Missing 'title' or 'summary'" in result.error_details["message"]

    # Verify no tasks created in PostgreSQL
    count = (await db_session.execute(select(Task))).scalars().all()
    assert len(count) == 0

    # Verify MongoDB record updated to FAILED
    detail = TaskImportService.get_import_by_id(result.import_id)
    assert detail.status == "FAILED"
    assert detail.error_details is not None


async def test_import_raw_task_nonexistent_project_fails(db_session: AsyncSession) -> None:
    raw = {
        "title": "Task for Ghost Project",
        "project_id": 999999,
        "priority": "medium",
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "Project 999999 not found" in str(result.error_details.get("message"))

    # Verify PostgreSQL rollback
    count = (await db_session.execute(select(Task))).scalars().all()
    assert len(count) == 0


async def test_import_raw_task_invalid_priority_fails(db_session: AsyncSession) -> None:
    project = await _create_test_project(db_session)
    raw = {
        "title": "Task with Invalid Priority",
        "project_id": project.id,
        "priority": "SUPER_URGENT",
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "Invalid priority" in str(result.error_details.get("message"))


async def test_import_raw_task_non_member_assignee_fails(db_session: AsyncSession) -> None:
    from app.models.project_user import ProjectRole, ProjectUser

    project = await _create_test_project(db_session)
    owner = await _create_test_user(db_session, email="owner@example.com")
    db_session.add(ProjectUser(project_id=project.id, user_id=owner.id, role=ProjectRole.owner))
    await db_session.commit()

    non_member = await _create_test_user(db_session, email="nonmember@example.com")
    raw = {
        "title": "Task with Non-Member Assignee",
        "project_id": project.id,
        "assignee_id": non_member.id,
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    msg = str(result.error_details.get("message", "")).lower()
    assert "membership" in msg or "not a member" in msg


def test_get_import_by_id_invalid_id() -> None:
    with pytest.raises(NotFoundError):
        TaskImportService.get_import_by_id("not-a-valid-object-id")


def test_get_import_by_id_not_found() -> None:
    with pytest.raises(NotFoundError):
        TaskImportService.get_import_by_id("6701a2b3c4d5e6f7a8b9c0d1")


async def test_import_raw_tasks_batch(db_session: AsyncSession) -> None:
    project = await _create_test_project(
        db_session, name="Service Batch Proj", slug="svc-batch-proj"
    )
    items = [
        {"summary": "Batch Item 1", "project_id": project.id, "priority": "high"},
        {"summary": "Batch Item 2", "project_id": project.id, "priority": "medium"},
        {"summary": "Batch Item 3 (Fail)", "project_id": 999999, "priority": "low"},
    ]

    total, succeeded, failed, results = await TaskImportService.import_raw_tasks_batch(
        db_session, items
    )

    assert total == 3
    assert succeeded == 2
    assert failed == 1
    assert len(results) == 3
    assert results[0].status == "SUCCESS"
    assert results[1].status == "SUCCESS"
    assert results[2].status == "FAILED"
