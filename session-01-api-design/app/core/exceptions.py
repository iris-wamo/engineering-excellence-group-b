"""Application errors, error response schemas, and FastAPI exception handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Response schemas


class ErrorDetail(BaseModel):
    field: str | None = Field(default=None, description="The field that caused the error")
    message: str = Field(description="Human-readable explanation for this detail")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code (UPPER_SNAKE)")
    message: str = Field(description="A human-readable explanation specific to this error")
    details: list[ErrorDetail] = Field(default_factory=list, description="A list of detailed errors")


class ErrorResponse(BaseModel):
    error: ErrorBody = Field(description="The error details")


# Exception hierarchy


class AppError(Exception):
    """Base class for all application errors."""

    code: str = "APP_ERROR"
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, details: list[dict] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND


class ValidationAppError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT


# Handlers


def error_json(status_code, code, message, details=None):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            }
        },
    )


async def handle_app_error(request, exc):
    return error_json(exc.status_code, exc.code, exc.message, exc.details)


async def handle_validation(request, exc):
    details = []
    for e in exc.errors():
        details.append({
            "field": str(e["loc"][-1]),
            "message": e["msg"],
        })
    return error_json(422, "VALIDATION_ERROR", "Invalid request payload", details)


async def handle_unexpected(request, exc):
    logger.exception("Unexpected error")
    return error_json(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred")


def register_exception_handlers(app: FastAPI):
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(Exception, handle_unexpected)
