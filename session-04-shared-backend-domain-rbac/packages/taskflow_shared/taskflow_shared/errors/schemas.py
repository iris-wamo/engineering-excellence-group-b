"""Canonical error response schemas (ADR-001)."""

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Specific field-level or validation error detail."""

    field: str | None = Field(default=None, description="The field that caused the error")
    message: str = Field(description="Human-readable explanation for this detail")


class ErrorBody(BaseModel):
    """Standardized error envelope body."""

    code: str = Field(description="Stable machine-readable error code (UPPER_SNAKE)")
    message: str = Field(description="A human-readable explanation specific to this error")
    details: list[ErrorDetail] = Field(
        default_factory=list, description="A list of detailed errors"
    )


class ErrorResponse(BaseModel):
    """Top-level error response model."""

    error: ErrorBody = Field(description="The error details")
