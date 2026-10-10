"""Base schema contracts for Pydantic models in TaskFlow."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base schema enabling ORM mode and attribute access."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampedSchema(BaseSchema):
    """Base schema for models with creation and update timestamps."""

    created_at: datetime = Field(description="Record creation timestamp (UTC)")
    updated_at: datetime = Field(description="Record last updated timestamp (UTC)")


class RawImportRecord(TimestampedSchema):
    """Base schema contract for raw import staging and audit records."""

    import_id: str = Field(description="Unique identifier for raw import record")
    status: str = Field(description="Processing status of import (e.g. PENDING, SUCCESS, FAILED)")
    error_details: dict[str, Any] | None = Field(
        default=None, description="Diagnostic error details if failed"
    )


class BatchImportRecord(BaseSchema):
    """Base schema contract for batch import operation results."""

    total: int = Field(ge=0, description="Total number of items in batch")
    succeeded: int = Field(ge=0, description="Number of successfully imported items")
    failed: int = Field(ge=0, description="Number of failed import items")
