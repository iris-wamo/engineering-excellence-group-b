"""Application errors, error response schemas, and FastAPI exception handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# User-api errors (predate the shared AppError hierarchy below; kept as-is
# per ADR-001 so user-api's response contract is left untouched).


class EmailAlreadyExistsError(HTTPException):
    """Raised when a user attempts to create an account with an existing email."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")


class UserNotFoundError(HTTPException):
    """Raised when a requested user cannot be found."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


# Shared AppError hierarchy (ADR-001), used by the project resource onward.


class ErrorDetail(BaseModel):
    field: str | None = Field(default=None, description="The field that caused the error")
    message: str = Field(description="Human-readable explanation for this detail")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code (UPPER_SNAKE)")
    message: str = Field(description="A human-readable explanation specific to this error")
    details: list[ErrorDetail] = Field(
        default_factory=list, description="A list of detailed errors"
    )


class ErrorResponse(BaseModel):
    error: ErrorBody = Field(description="The error details")


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


def error_json(status_code: int, code: str, message: str, details: list[dict] | None = None):
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


async def handle_app_error(request, exc: AppError):
    return error_json(exc.status_code, exc.code, exc.message, exc.details)


async def handle_validation(request, exc: RequestValidationError):
    details = [{"field": str(e["loc"][-1]), "message": e["msg"]} for e in exc.errors()]
    return error_json(422, "VALIDATION_ERROR", "Invalid request payload", details)


async def handle_unexpected(request, exc: Exception):
    logger.exception("Unexpected error")
    return error_json(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(Exception, handle_unexpected)
