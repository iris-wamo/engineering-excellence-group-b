"""Integration and unit tests for TaskImportService."""

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.mongo import get_raw_task_imports_collection
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.task_import_service import TaskImportService


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
    detail = await TaskImportService.get_import_by_id(result.import_id)
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
    assert "Title" in result.error_details["message"] or "title" in result.error_details["message"]

    # Verify no tasks created in PostgreSQL
    count = (await db_session.execute(select(Task))).scalars().all()
    assert len(count) == 0

    # Verify MongoDB record updated to FAILED
    detail = await TaskImportService.get_import_by_id(result.import_id)
    assert detail.status == "FAILED"
    assert detail.error_details is not None


async def test_import_raw_task_whitespace_title_falls_back_to_summary(
    db_session: AsyncSession,
) -> None:
    project = await _create_test_project(db_session, name="Fallback Proj", slug="fallback-proj")
    raw = {
        "title": "   ",
        "summary": "Recovered from Summary",
        "project_id": project.id,
        "priority": "high",
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "SUCCESS"
    assert result.postgres_task_id is not None
    task = await db_session.get(Task, result.postgres_task_id)
    assert task is not None
    assert task.title == "Recovered from Summary"


async def test_import_raw_task_title_over_100_chars_fails(db_session: AsyncSession) -> None:
    project = await _create_test_project(db_session, name="Long Proj", slug="long-proj")
    raw = {
        "title": "A" * 101,
        "project_id": project.id,
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "100" in result.error_details["message"]


async def test_import_raw_task_non_string_description_fails(db_session: AsyncSession) -> None:
    project = await _create_test_project(db_session, name="Dict Desc Proj", slug="dict-desc-proj")
    raw = {
        "title": "Task with Dict Description",
        "description": {"some": "nested_object"},
        "project_id": project.id,
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "Description must be a string" in result.error_details["message"]


async def test_import_raw_task_boolean_project_id_fails(db_session: AsyncSession) -> None:
    raw = {
        "title": "Task with boolean project_id",
        "project_id": True,
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "boolean" in result.error_details["message"].lower()


async def test_import_raw_task_float_project_id_fails(db_session: AsyncSession) -> None:
    raw = {
        "title": "Task with fractional project_id",
        "project_id": 1.9,
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "fractional" in result.error_details["message"].lower()


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


async def test_post_commit_mongo_failure_does_not_report_failed(
    db_session: AsyncSession,
) -> None:
    """When Mongo update fails after Postgres commit, do NOT report FAILED."""
    project = await _create_test_project(
        db_session, name="Post Commit Proj", slug="post-commit-proj"
    )
    raw = {
        "title": "Task Committed To Postgres",
        "project_id": project.id,
    }

    col = get_raw_task_imports_collection()

    # Allow initial update or fail on stage 2 update
    call_count = 0

    async def mock_update_one(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        # The update to SUCCESS is the first update_one call in this flow
        raise ConnectionError("Simulated Mongo network failure post-commit")

    with patch.object(col, "update_one", side_effect=mock_update_one):
        result = await TaskImportService.import_raw_task(db_session, raw, collection=col)

    # Must NOT report FAILED because the Postgres task was committed!
    assert result.status == "SUCCESS"
    assert result.postgres_task_id is not None
    assert result.error_details is None

    # Verify task exists in PostgreSQL
    task = await db_session.get(Task, result.postgres_task_id)
    assert task is not None
    assert task.title == "Task Committed To Postgres"


async def test_idempotent_import_avoids_duplicate_tasks(db_session: AsyncSession) -> None:
    """Sending the same idempotency key twice returns the same import and task."""
    project = await _create_test_project(db_session, name="Idem Proj", slug="idem-proj")
    raw = {
        "title": "Sync from external system",
        "project_id": project.id,
        "jira_key": "PROJ-1001",
    }

    res1 = await TaskImportService.import_raw_task(db_session, raw)
    assert res1.status == "SUCCESS"
    assert res1.postgres_task_id is not None

    # Second call with the same jira_key / payload
    res2 = await TaskImportService.import_raw_task(db_session, raw)
    assert res2.status == "SUCCESS"
    assert res2.import_id == res1.import_id
    assert res2.postgres_task_id == res1.postgres_task_id

    # Verify only 1 task in database
    tasks = (
        (await db_session.execute(select(Task).where(Task.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(tasks) == 1


async def test_import_raw_tasks_batch_mid_batch_failure_preserves_other_commits(
    db_session: AsyncSession,
) -> None:
    """Batch with a mid-batch error: later items still process, earlier commits remain."""
    project = await _create_test_project(db_session, name="Mid Batch Proj", slug="mid-batch-proj")
    items = [
        {"summary": "Batch 1 (Success)", "project_id": project.id, "priority": "high"},
        {
            "summary": "Batch 2 (Fail - Nonexistent Proj)",
            "project_id": 999999,
            "priority": "medium",
        },
        {"summary": "Batch 3 (Success)", "project_id": project.id, "priority": "low"},
    ]

    total, succeeded, failed, results = await TaskImportService.import_raw_tasks_batch(
        db_session, items
    )

    assert total == 3
    assert succeeded == 2
    assert failed == 1
    assert results[0].status == "SUCCESS"
    assert results[1].status == "FAILED"
    assert results[2].status == "SUCCESS"

    # Verify item 0 and item 2 exist in PostgreSQL
    t1 = await db_session.get(Task, results[0].postgres_task_id)
    t3 = await db_session.get(Task, results[2].postgres_task_id)
    assert t1 is not None and t1.title == "Batch 1 (Success)"
    assert t3 is not None and t3.title == "Batch 3 (Success)"


async def test_unexpected_database_error_shields_client(db_session: AsyncSession) -> None:
    """Unexpected DB errors return sanitized error details without leaking SQL text."""
    project = await _create_test_project(db_session, name="Shield Proj", slug="shield-proj")
    raw = {
        "title": "Shielded Error Task",
        "project_id": project.id,
    }

    err_msg = "psycopg.OperationalError: raw SQL SELECT * FROM ..."
    with patch.object(db_session, "commit", side_effect=RuntimeError(err_msg)):
        result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert result.error_details["type"] == "InternalNormalizationError"
    assert "raw SQL" not in result.error_details["message"]
    assert "internal error occurred" in result.error_details["message"].lower()


async def test_get_import_by_id_invalid_id() -> None:
    with pytest.raises(NotFoundError):
        await TaskImportService.get_import_by_id("not-a-valid-object-id")


async def test_get_import_by_id_not_found() -> None:
    with pytest.raises(NotFoundError):
        await TaskImportService.get_import_by_id("6701a2b3c4d5e6f7a8b9c0d1")
