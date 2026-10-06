"""Schemas for raw task imports and normalization."""

from typing import Any

from pydantic import BaseModel, Field
from taskflow_shared.contracts import RawImportRecord
from taskflow_shared.enums import ImportStatus


class TaskRawImportRequest(BaseModel):
    """Schema for requesting a raw task import."""

    raw_payload: dict[str, Any] = Field(
        ...,
        description="Arbitrary raw task payload from external source (e.g. Jira, Trello).",
        examples=[
            {
                "summary": "Implement OAuth2 SSO",
                "project_id": 1,
                "priority": "high",
                "status": "in_progress",
                "jira_key": "SEC-402",
            }
        ],
    )


class TaskImportResponse(RawImportRecord):
    """Schema for raw task import status response."""

    status: ImportStatus = Field(  # type: ignore[assignment]
        ...,
        description="Import status: PENDING, SUCCESS, or FAILED.",
        examples=[ImportStatus.SUCCESS, ImportStatus.FAILED],
    )
    postgres_task_id: int | None = Field(
        default=None,
        description="Normalized PostgreSQL task ID when status is SUCCESS.",
    )


class TaskImportDetailResponse(TaskImportResponse):
    """Schema for detailed raw task import record including original payload."""

    raw_payload: dict[str, Any] = Field(
        ...,
        description="Original raw payload preserved in MongoDB.",
    )


class TaskBatchImportRequest(BaseModel):
    """Schema for requesting a batch raw task import."""

    items: list[TaskRawImportRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of raw task import items (max 100 per batch).",
    )


class TaskBatchImportResponse(BaseModel):
    """Schema for batch task import execution results."""

    total: int = Field(ge=0, description="Total number of tasks submitted in batch.")
    succeeded: int = Field(ge=0, description="Tasks successfully normalized into PostgreSQL.")
    failed: int = Field(ge=0, description="Tasks that failed validation or normalization.")
    results: list[TaskImportResponse] = Field(
        ...,
        description="Individual import results for each item in the batch.",
    )
