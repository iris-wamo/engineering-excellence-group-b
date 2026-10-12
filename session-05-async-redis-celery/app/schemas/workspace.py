"""Pydantic schemas for workspace request and response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceCreate(BaseModel):
    """Schema for creating a new workspace."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Workspace name",
        examples=["Acme Corp", "Globex Corp"],
    )
    description: str | None = Field(
        None,
        max_length=1000,
        description="Workspace description (optional)",
        examples=["Primary corporate tenant"],
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Workspace name cannot be empty or whitespace only")
        return cleaned


class WorkspaceResponse(BaseModel):
    """Schema for returning workspace details."""

    id: int = Field(description="Unique workspace ID")
    name: str = Field(description="Workspace name")
    slug: str = Field(description="Workspace unique slug")
    description: str | None = Field(None, description="Workspace description")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    "name": "Default Workspace",
                    "slug": "default-workspace",
                    "description": "System default workspace",
                    "created_at": "2026-10-11T00:00:00Z",
                    "updated_at": "2026-10-11T00:00:00Z",
                }
            ]
        },
    )
