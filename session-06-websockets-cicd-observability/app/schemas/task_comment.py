from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from taskflow_shared.pagination import PaginatedResponse


class TaskCommentCreate(BaseModel):
    content: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Comment text (required, 1-2000 characters).",
        examples=["This task is almost complete."],
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Content cannot be empty or whitespace only.")
        return cleaned


class TaskCommentResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    content: str
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    "task_id": 7,
                    "user_id": 5,
                    "content": "This task is almost complete.",
                    "created_at": "2026-11-19T09:30:00Z",
                }
            ]
        },
    )


class TaskCommentListResponse(PaginatedResponse[TaskCommentResponse]):
    """Schema for the paginated task comment list response."""
