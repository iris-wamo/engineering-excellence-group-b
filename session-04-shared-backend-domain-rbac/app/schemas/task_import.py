"""Schemas for raw task imports and normalization."""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from taskflow_shared.contracts import RawImportRecord
from taskflow_shared.enums import ImportStatus

from app.models.enums import TaskPriority, TaskStatus


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


class NormalizedTaskPayload(BaseModel):
    """Schema for validating mapped raw task payload before relational persistence."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Task title (1-100 characters).",
    )
    description: str | None = Field(
        default=None,
        description="Optional task description.",
    )
    project_id: int = Field(
        ...,
        description="Target project ID.",
    )
    assignee_id: int | None = Field(
        default=None,
        description="Optional assignee user ID.",
    )
    priority: TaskPriority = Field(
        default=TaskPriority.medium,
        description="Normalized task priority.",
    )
    status: TaskStatus = Field(
        default=TaskStatus.todo,
        description="Normalized task status.",
    )
    due_date: date | None = Field(
        default=None,
        description="Optional task due date.",
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Title cannot be empty or whitespace only.")
        if len(cleaned) > 100:
            raise ValueError("Title cannot exceed 100 characters.")
        return cleaned

    @field_validator("description", mode="before")
    @classmethod
    def validate_description(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Description must be a string.")
        return value

    @field_validator("project_id", "assignee_id", mode="before")
    @classmethod
    def validate_integer_fields(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("Invalid integer: booleans are not allowed.")
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError("Invalid integer: fractional numbers are not allowed.")
            return int(value)
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed.isdigit() and not (trimmed.startswith("-") and trimmed[1:].isdigit()):
                raise ValueError(f"Invalid integer string: '{value}'.")
            return int(trimmed)
        if isinstance(value, int):
            return value
        raise ValueError(f"Invalid integer: {value}.")

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> Any:
        if value is None:
            return TaskStatus.todo
        if isinstance(value, str):
            cleaned = value.strip().lower()
            try:
                return TaskStatus(cleaned)
            except ValueError as exc:
                raise ValueError(f"Invalid status '{value}'.") from exc
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority(cls, value: Any) -> Any:
        if value is None:
            return TaskPriority.medium
        if isinstance(value, str):
            cleaned = value.strip().lower()
            try:
                return TaskPriority(cleaned)
            except ValueError as exc:
                raise ValueError(f"Invalid priority '{value}'.") from exc
        return value

    @field_validator("due_date", mode="before")
    @classmethod
    def validate_due_date(cls, value: Any) -> Any:
        if not value:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.split("T")[0])
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid due_date format: '{value}'.") from exc
        raise ValueError(f"Invalid due_date: {value}.")


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
