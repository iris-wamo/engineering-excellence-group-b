"""Pydantic schemas for task request and response models."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TaskPriority, TaskStatus


class TaskCreate(BaseModel):
    """Schema for creating a new task."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Task title (required, 1-100 characters).",
        examples=["Implement login API"],
    )

    description: str | None = Field(
        None,
        description="Task description (optional).",
        examples=["Implement JWT authentication."],
    )

    project_id: int = Field(
        ...,
        description="Project ID to which the task belongs.",
        examples=[1],
    )

    assignee_id: int | None = Field(
        None,
        description="Assigned user ID (optional).",
        examples=[5],
    )

    priority: TaskPriority = Field(
        default=TaskPriority.medium,
        description="Task priority.",
        examples=["medium"],
    )

    due_date: date | None = Field(
        None,
        description="Task due date (YYYY-MM-DD).",
        examples=["2026-07-26"],
    )


class TaskStatusUpdate(BaseModel):
    """Schema for updating task status."""

    status: TaskStatus = Field(
        ...,
        description="Updated task status.",
        examples=["todo", "in_progress", "done"],
    )


class TaskResponse(BaseModel):
    """Schema for returning task details."""

    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    project_id: int
    assignee_id: int | None
    due_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    "title": "Implement login API",
                    "description": "Implement JWT authentication",
                    "project_id": 1,
                    "assignee_id": 5,
                    "status": "todo",
                    "priority": "high",
                    "due_date": "2026-08-10",
                    "created_at": "2026-07-26T09:30:00Z",
                    "updated_at": "2026-07-26T11:00:00Z",
                }
            ]
        },
    )


class TaskListResponse(BaseModel):
    """Schema for paginated task list response."""

    items: list[TaskResponse]
    total: int
    page: int
    page_size: int