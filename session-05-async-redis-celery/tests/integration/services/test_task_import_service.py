"""Integration and unit tests for TaskImportService."""

from unittest.mock import MagicMock, patch

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.mongo import get_raw_task_imports_collection
from app.events.schemas import TaskEventType
from app.models.enums import ProjectRole
from app.models.notification import Notification
from app.models.task import Task
from app.services.task_import_service import TaskImportService
from tests.fixtures.events import stream_events
from tests.fixtures.factories import MISSING_ID, DataFactory


async def test_import_raw_task_success(db_session: AsyncSession, factory: DataFactory) -> None:
    project = await factory.project()
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


async def test_import_raw_task_missing_title_fails(
    db_session: AsyncSession, factory: DataFactory
) -> None:
    project = await factory.project()
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
    factory: DataFactory,
) -> None:
    project = await factory.project(name="Fallback Proj")
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


async def test_import_raw_task_title_over_100_chars_fails(
    db_session: AsyncSession, factory: DataFactory
) -> None:
    project = await factory.project(name="Long Proj")
    raw = {
        "title": "A" * 101,
        "project_id": project.id,
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert "100" in result.error_details["message"]


async def test_import_raw_task_non_string_description_fails(
    db_session: AsyncSession, factory: DataFactory
) -> None:
    project = await factory.project(name="Dict Desc Proj")
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
        "project_id": MISSING_ID,
        "priority": "medium",
    }

    result = await TaskImportService.import_raw_task(db_session, raw)

    assert result.status == "FAILED"
    assert result.postgres_task_id is None
    assert result.error_details is not None
    assert f"Project {MISSING_ID} not found" in str(result.error_details.get("message"))

    # Verify PostgreSQL rollback
    count = (await db_session.execute(select(Task))).scalars().all()
    assert len(count) == 0


async def test_import_raw_task_invalid_priority_fails(
    db_session: AsyncSession, factory: DataFactory
) -> None:
    project = await factory.project()
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


async def test_import_raw_task_non_member_assignee_fails(
    db_session: AsyncSession, factory: DataFactory
) -> None:
    from app.models.enums import ProjectRole

    project = await factory.project()
    owner = await factory.user(email="owner@example.com")
    await factory.grant_role(owner, project, ProjectRole.owner)

    non_member = await factory.user(email="nonmember@example.com")
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
    factory: DataFactory,
) -> None:
    """When Mongo update fails after Postgres commit, do NOT report FAILED."""
    project = await factory.project(name="Post Commit Proj")
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


async def test_idempotent_import_avoids_duplicate_tasks(
    db_session: AsyncSession, factory: DataFactory
) -> None:
    """Sending the same idempotency key twice returns the same import and task."""
    project = await factory.project(name="Idem Proj")
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
    factory: DataFactory,
) -> None:
    """Batch with a mid-batch error: later items still process, earlier commits remain."""
    project = await factory.project(name="Mid Batch Proj")
    items = [
        {"summary": "Batch 1 (Success)", "project_id": project.id, "priority": "high"},
        {
            "summary": "Batch 2 (Fail - Nonexistent Proj)",
            "project_id": MISSING_ID,
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


async def test_unexpected_database_error_shields_client(
    db_session: AsyncSession, factory: DataFactory
) -> None:
    """Unexpected DB errors return sanitized error details without leaking SQL text."""
    project = await factory.project(name="Shield Proj")
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


async def test_idempotent_retry_reconciles_pending_import_after_post_commit_failure(
    db_session: AsyncSession,
    factory: DataFactory,
) -> None:
    """When post-commit Mongo update fails, an idempotent retry self-heals PENDING to SUCCESS."""
    project = await factory.project(name="Reconcile Proj")
    raw = {
        "title": "Idempotent Reconcile Task",
        "project_id": project.id,
        "jira_key": "RECON-101",
    }
    col = get_raw_task_imports_collection()

    # Step 1: Simulate post-commit Mongo failure on initial attempt
    with patch.object(col, "update_one", side_effect=ConnectionError("Simulated Mongo failure")):
        first_result = await TaskImportService.import_raw_task(db_session, raw, collection=col)

    # In Postgres, task was committed
    assert first_result.postgres_task_id is not None
    committed_task_id = first_result.postgres_task_id

    # In MongoDB, document was left in PENDING because update_one failed
    doc = await col.find_one({"idempotency_key": "RECON-101"})
    assert doc is not None
    assert doc["status"] == "PENDING"
    assert doc["postgres_task_id"] is None

    # Step 2: Retry with the same idempotency key (normal Mongo operation)
    retry_result = await TaskImportService.import_raw_task(db_session, raw, collection=col)

    # Verification: Result should be reconciled to SUCCESS with the committed task ID
    assert retry_result.status == "SUCCESS"
    assert retry_result.postgres_task_id == committed_task_id
    assert retry_result.import_id == str(doc["_id"])

    # MongoDB document should now be updated to SUCCESS
    updated_doc = await col.find_one({"_id": doc["_id"]})
    assert updated_doc is not None
    assert updated_doc["status"] == "SUCCESS"
    assert updated_doc["postgres_task_id"] == committed_task_id


async def test_idempotent_retry_on_uncommitted_pending_record_stays_pending(
    db_session: AsyncSession,
) -> None:
    """When a pending import has no matching Postgres task, retry preserves PENDING."""
    from datetime import UTC, datetime

    col = get_raw_task_imports_collection()
    doc_res = await col.insert_one(
        {
            "raw_payload": {"title": "In flight task"},
            "idempotency_key": "IN-FLIGHT-999",
            "status": "PENDING",
            "postgres_task_id": None,
            "error_details": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )

    raw = {"title": "In flight task", "idempotency_key": "IN-FLIGHT-999"}
    result = await TaskImportService.import_raw_task(db_session, raw, collection=col)

    assert result.status == "PENDING"
    assert result.postgres_task_id is None
    assert result.import_id == str(doc_res.inserted_id)


async def test_import_with_assignee_stages_notification_and_publishes_assigned_event(
    db_session: AsyncSession,
    factory: DataFactory,
    redis_client: Redis,
    broker_publish: MagicMock,
) -> None:
    """An imported task with an assignee is an assignment, like create_task with one."""
    project = await factory.project()
    importer = await factory.member(project, ProjectRole.owner)
    assignee = await factory.member(project)
    raw = {"title": "Imported With Assignee", "project_id": project.id, "assignee_id": assignee.id}

    result = await TaskImportService.import_raw_task(db_session, raw, actor_id=importer.id)

    assert result.status == "SUCCESS"
    notification = await db_session.scalar(
        select(Notification).where(Notification.task_id == result.postgres_task_id)
    )
    assert notification is not None
    assert notification.status == "pending"
    assert notification.recipient_id == assignee.id
    assert notification.payload == {
        "task_id": result.postgres_task_id,
        "task_title": "Imported With Assignee",
        "assigned_by_id": importer.id,
    }
    broker_publish.assert_called_once_with(kwargs={"notification_id": notification.id}, retry=False)
    [event] = await stream_events(redis_client)
    assert event.event_type is TaskEventType.assigned
    assert event.task_id == result.postgres_task_id
    assert event.actor_id == importer.id
    assert event.data == {"previous_assignee_id": None, "new_assignee_id": assignee.id}


async def test_import_without_assignee_has_no_notification_or_event(
    db_session: AsyncSession,
    factory: DataFactory,
    redis_client: Redis,
    broker_publish: MagicMock,
) -> None:
    project = await factory.project()

    result = await TaskImportService.import_raw_task(
        db_session, {"title": "Imported Unassigned", "project_id": project.id}
    )

    assert result.status == "SUCCESS"
    broker_publish.assert_not_called()
    assert await stream_events(redis_client) == []
    assert (
        await db_session.scalar(
            select(Notification).where(Notification.task_id == result.postgres_task_id)
        )
        is None
    )


async def test_idempotent_import_retry_does_not_notify_again(
    db_session: AsyncSession,
    factory: DataFactory,
    redis_client: Redis,
    broker_publish: MagicMock,
) -> None:
    """A retried import returns the existing task without a second assignment."""
    project = await factory.project()
    assignee = await factory.member(project)
    raw = {"title": "Retried Import", "project_id": project.id, "assignee_id": assignee.id}

    first = await TaskImportService.import_raw_task(db_session, raw, idempotency_key="retry-1")
    second = await TaskImportService.import_raw_task(db_session, raw, idempotency_key="retry-1")

    assert second.postgres_task_id == first.postgres_task_id
    notifications = (
        await db_session.scalars(
            select(Notification).where(Notification.task_id == first.postgres_task_id)
        )
    ).all()
    assert len(notifications) == 1
    assert broker_publish.call_count == 1
    assert len(await stream_events(redis_client)) == 1
