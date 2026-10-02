"""Base schema contracts for Pydantic models in TaskFlow."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base schema enabling ORM mode and attribute access."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampedSchema(BaseSchema):
    """Base schema for models with creation and update timestamps."""

    created_at: datetime = Field(description="Record creation timestamp (UTC)")
    updated_at: datetime = Field(description="Record last updated timestamp (UTC)")
