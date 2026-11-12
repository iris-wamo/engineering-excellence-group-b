"""Unit tests for TaskSummaryResponse and ExternalServiceResult schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.task import ExternalServiceResult, TaskSummaryResponse


def test_external_service_result_serialization() -> None:
    res = ExternalServiceResult(
        service="workload_service",
        status="healthy",
        latency_ms=125.4,
        mode="async",
    )
    data = res.model_dump()
    assert data["service"] == "workload_service"
    assert data["status"] == "healthy"
    assert data["latency_ms"] == 125.4
    assert data["mode"] == "async"


def test_task_summary_response_valid() -> None:
    ext = ExternalServiceResult(
        service="workload_service",
        status="healthy",
        latency_ms=50.0,
        mode="async",
    )
    summary = TaskSummaryResponse(
        workspace_id=1,
        counts_by_status={"todo": 4, "in_progress": 2, "review": 1, "done": 10},
        overdue_count=2,
        assigned_count=8,
        total_count=17,
        external_service=ext,
    )
    data = summary.model_dump()
    assert data["workspace_id"] == 1
    assert data["counts_by_status"]["todo"] == 4
    assert data["overdue_count"] == 2
    assert data["assigned_count"] == 8
    assert data["total_count"] == 17
    assert data["external_service"]["status"] == "healthy"


def test_task_summary_response_requires_all_fields() -> None:
    with pytest.raises(ValidationError):
        TaskSummaryResponse(  # type: ignore[call-arg]
            workspace_id=1,
            counts_by_status={"todo": 1},
            # Missing overdue_count, assigned_count, total_count, external_service
        )


def test_external_service_result_rejects_negative_latency() -> None:
    """ExternalServiceResult rejects negative latency_ms."""
    with pytest.raises(ValidationError):
        ExternalServiceResult(
            service="workload_service",
            status="healthy",
            latency_ms=-1.0,
            mode="async",
        )


def test_task_summary_response_round_trip_json() -> None:
    """model_dump(mode='json') works and nested external_service is a dict."""
    ext = ExternalServiceResult(
        service="workload_service",
        status="healthy",
        latency_ms=75.5,
        mode="async",
    )
    summary = TaskSummaryResponse(
        workspace_id=1,
        counts_by_status={"todo": 3, "in_progress": 1, "review": 0, "done": 2},
        overdue_count=1,
        assigned_count=4,
        total_count=6,
        external_service=ext,
    )
    dumped = summary.model_dump(mode="json")
    assert isinstance(dumped, dict)
    assert isinstance(dumped["external_service"], dict)
    assert dumped["external_service"]["service"] == "workload_service"
    assert dumped["external_service"]["latency_ms"] == 75.5
    assert dumped["external_service"]["mode"] == "async"

    # Verify round-trip validation restores equivalent model
    validated = TaskSummaryResponse.model_validate(dumped)
    assert validated.workspace_id == summary.workspace_id
    assert validated.external_service.latency_ms == summary.external_service.latency_ms
