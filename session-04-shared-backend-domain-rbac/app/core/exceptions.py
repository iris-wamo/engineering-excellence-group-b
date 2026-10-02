"""Application errors, error response schemas, and FastAPI exception handlers.

Re-exports core error foundations from taskflow_shared while defining
app-specific error specializations.
"""

from __future__ import annotations

from fastapi import status
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

__all__ = [
    "AppError",
    "NotFoundError",
    "ConflictError",
    "ValidationAppError",
    "UnauthorizedError",
    "ForbiddenError",
    "DomainError",
    "ErrorDetail",
    "ErrorBody",
    "ErrorResponse",
    "EmailAlreadyExistsError",
    "UserNotFoundError",
    "ProjectMembershipRequiredError",
    "TransactionSimulationError",
    "register_exception_handlers",
]


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
