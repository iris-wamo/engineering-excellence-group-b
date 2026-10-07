"""Application errors, error response schemas, and FastAPI exception handlers.

Re-exports unified error foundations from taskflow_shared
and defines concrete TaskFlow domain errors.
"""

from __future__ import annotations

from typing import Any

from taskflow_shared.errors import (
    AppError,
    ConflictError,
    DomainError,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationAppError,
    register_exception_handlers,
)


class EmailAlreadyExistsError(ConflictError):
    """Raised when a user attempts to create an account with an existing email."""

    def __init__(
        self,
        message: str = "Email already exists",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            message,
            details=details or [{"field": "email", "message": "Email already exists"}],
        )


class UserNotFoundError(NotFoundError):
    """Raised when a requested user cannot be found."""

    def __init__(
        self,
        message: str = "User not found",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            message,
            details=details or [{"field": "user_id", "message": "User does not exist"}],
        )


class ProjectMembershipRequiredError(AppError):
    """Raised when assigning a task to a user who is not a member of the project."""

    code = "PROJECT_MEMBERSHIP_REQUIRED"
    status_code = 400

    def __init__(
        self,
        user_id: int | None = None,
        project_id: int | None = None,
        message: str = "User is not a member of this project",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        resolved_details = details
        if resolved_details is None and user_id is not None and project_id is not None:
            resolved_details = [
                {
                    "field": "assignee_id",
                    "message": f"User {user_id} is not a member of project {project_id}",
                }
            ]
        super().__init__(message, details=resolved_details)


class TransactionSimulationError(AppError):
    """Raised when a transaction failure is simulated for demonstration or testing."""

    code = "SIMULATED_TRANSACTION_FAILURE"
    status_code = 500


__all__ = [
    "AppError",
    "NotFoundError",
    "ConflictError",
    "ValidationAppError",
    "UnauthorizedError",
    "ForbiddenError",
    "DomainError",
    "EmailAlreadyExistsError",
    "UserNotFoundError",
    "ProjectMembershipRequiredError",
    "TransactionSimulationError",
    "ErrorDetail",
    "ErrorBody",
    "ErrorResponse",
    "register_exception_handlers",
]
