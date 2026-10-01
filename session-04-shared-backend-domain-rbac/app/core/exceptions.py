"""Application errors, error response schemas, and FastAPI exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Shared AppError hierarchy (ADR-001).


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

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None) -> None:
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


class EmailAlreadyExistsError(ConflictError):
    """Raised when a user attempts to create an account with an existing email."""

    def __init__(self) -> None:
        super().__init__(
            "Email already exists",
            details=[{"field": "email", "message": "Email already exists"}],
        )


class UserNotFoundError(NotFoundError):
    """Raised when a requested user cannot be found."""

    def __init__(self) -> None:
        super().__init__(
            "User not found",
            details=[{"field": "user_id", "message": "User does not exist"}],
        )


class ProjectMembershipRequiredError(AppError):
    """Raised when assigning a task to a user who is not a member of the project."""

    code = "PROJECT_MEMBERSHIP_REQUIRED"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, user_id: int, project_id: int) -> None:
        super().__init__(
            "User is not a member of this project",
            details=[
                {
                    "field": "assignee_id",
                    "message": f"User {user_id} is not a member of project {project_id}",
                }
            ],
        )


class TransactionSimulationError(AppError):
    """Raised when a transaction failure is simulated for demonstration or testing."""

    code = "SIMULATED_TRANSACTION_FAILURE"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR


def error_json(
    status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
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


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise exc
    return error_json(exc.status_code, exc.code, exc.message, exc.details)


async def handle_validation(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    details = [{"field": str(e["loc"][-1]), "message": e["msg"]} for e in exc.errors()]
    return error_json(422, "VALIDATION_ERROR", "Invalid request payload", details)


async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unexpected error")
    return error_json(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(Exception, handle_unexpected)
