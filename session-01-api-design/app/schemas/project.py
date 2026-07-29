"""Pydantic schemas for project request/response models."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    """Schema for creating a new project."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        strip_whitespace=True,
        description="Project name (required, 1-150 characters)",
        examples=["PeopleUp", "Actovio"],
    )
    description: str | None = Field(
        None,
        max_length=1000,
        description="Project description (optional, max 1000 characters)",
        examples=[
            "Comprehensive HR management platform with talent analytics",
            None,
        ],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "PeopleUp",
                    "description": (
                        "Your 360 HRM solution - unified talent management "
                        "with real-time employee insights, performance "
                        "tracking, and organizational development tools"
                    ),
                },
                {
                    "name": "Actovio",
                    "description": (
                        "Track productivity of your employees with intelligent "
                        "activity monitoring, engagement analytics, and "
                        "actionable performance metrics for remote teams"
                    ),
                },
            ]
        }
    }

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is not empty or whitespace-only after stripping."""
        if not v or not v.strip():
            raise ValueError("Project name cannot be empty or contain only whitespace")
        return v.strip()

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """Ensure description (if provided) is not whitespace-only."""
        if v is not None and not v.strip():
            raise ValueError("Description cannot be empty or contain only whitespace")
        return v.strip() if v else None


class ProjectResponse(BaseModel):
    """Schema for returning project details."""

    id: int = Field(description="Unique project ID (auto-generated)")
    name: str = Field(description="Project name")
    description: str | None = Field(description="Project description (if provided)")
    created_at: datetime = Field(description="ISO 8601 timestamp of project creation")
    updated_at: datetime = Field(description="ISO 8601 timestamp of last update")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "name": "PeopleUp",
                    "description": (
                        "Your 360 HRM solution - unified talent management "
                        "with real-time employee insights, performance "
                        "tracking, and organizational development tools"
                    ),
                    "created_at": "2026-07-20T08:30:00+00:00",
                    "updated_at": "2026-07-26T14:15:00+00:00",
                },
                {
                    "id": 2,
                    "name": "Actovio",
                    "description": (
                        "Track productivity of your employees with intelligent "
                        "activity monitoring, engagement analytics, and "
                        "actionable performance metrics for remote teams"
                    ),
                    "created_at": "2026-07-22T11:45:00+00:00",
                    "updated_at": "2026-07-26T10:20:00+00:00",
                },
            ]
        },
    }


class ProjectListResponse(BaseModel):
    """Schema for a paginated project list response."""

    items: list[ProjectResponse] = Field(description="The projects on this page")
    total: int = Field(description="Total number of projects matching the query")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Maximum number of projects per page")
