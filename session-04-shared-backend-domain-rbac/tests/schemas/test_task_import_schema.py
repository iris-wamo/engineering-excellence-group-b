"""Unit tests for task import schemas."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskResponse
from app.schemas.task_import import (
    TaskImportDetailResponse,
    TaskImportResponse,
    TaskRawImportRequest,
)


def test_task_raw_import_request_valid() -> None:
    payload = {
        "raw_payload": {
            "summary": "Implement OAuth2",
            "project_id": 1,
            "priority": "high",
            "jira_key": "SEC-101",
        }
    }
    req = TaskRawImportRequest(**payload)
    assert req.raw_payload["summary"] == "Implement OAuth2"
    assert req.raw_payload["jira_key"] == "SEC-101"


def test_task_raw_import_request_missing_payload() -> None:
    with pytest.raises(ValidationError):
        TaskRawImportRequest()  # type: ignore[call-arg]


def test_task_import_response_serialization() -> None:
    now = datetime.now(UTC)
    resp = TaskImportResponse(
        import_id="6701a2b3c4d5e6f7a8b9c0d1",
        status="SUCCESS",
        postgres_task_id=42,
        error_details=None,
        created_at=now,
        updated_at=now,
    )
    data = resp.model_dump()
    assert data["import_id"] == "6701a2b3c4d5e6f7a8b9c0d1"
    assert data["status"] == "SUCCESS"
    assert data["postgres_task_id"] == 42
    assert data["error_details"] is None


def test_task_import_detail_response_includes_raw_payload() -> None:
    now = datetime.now(UTC)
    resp = TaskImportDetailResponse(
        import_id="6701a2b3c4d5e6f7a8b9c0d1",
        status="FAILED",
        postgres_task_id=None,
        error_details={"type": "ValueError", "message": "Project 99 not found"},
        raw_payload={"summary": "Broken import", "project_id": 99},
        created_at=now,
        updated_at=now,
    )
    data = resp.model_dump()
    assert data["status"] == "FAILED"
    assert data["raw_payload"]["summary"] == "Broken import"
    assert data["error_details"]["type"] == "ValueError"


def test_task_response_supports_mongo_import_id() -> None:
    now = datetime.now(UTC)
    task_resp = TaskResponse(
        id=1,
        title="Test Task",
        description="Test Description",
        status="todo",  # type: ignore[arg-type]
        priority="medium",  # type: ignore[arg-type]
        project_id=1,
        assignee_id=None,
        due_date=None,
        mongo_import_id="6701a2b3c4d5e6f7a8b9c0d1",
        created_at=now,
        updated_at=now,
    )
    assert task_resp.mongo_import_id == "6701a2b3c4d5e6f7a8b9c0d1"


def test_task_batch_import_schemas() -> None:
    from app.schemas.task_import import TaskBatchImportRequest, TaskBatchImportResponse

    # Valid batch request
    req = TaskBatchImportRequest(
        items=[
            TaskRawImportRequest(raw_payload={"summary": "Task 1", "project_id": 1}),
            TaskRawImportRequest(raw_payload={"summary": "Task 2", "project_id": 1}),
        ]
    )
    assert len(req.items) == 2

    # Empty batch rejected by min_length=1
    with pytest.raises(ValidationError):
        TaskBatchImportRequest(items=[])

    # Valid batch response
    resp = TaskBatchImportResponse(
        total=2,
        succeeded=2,
        failed=0,
        results=[],
    )
    assert resp.total == 2
    assert resp.succeeded == 2
    assert resp.failed == 0
