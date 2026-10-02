"""Shared AppError exception hierarchy."""

from typing import Any


class AppError(Exception):
    """Base class for all domain and application errors."""

    code: str = "APP_ERROR"
    status_code: int = 400

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None) -> None:
        self.message = message
        self.details = details or []
        super().__init__(message)


class NotFoundError(AppError):
    """Resource was not found."""

    code = "NOT_FOUND"
    status_code = 404


class ConflictError(AppError):
    """State conflict occurred (e.g. duplicate key or concurrency collision)."""

    code = "CONFLICT"
    status_code = 409


class ValidationAppError(AppError):
    """Domain validation error."""

    code = "VALIDATION_ERROR"
    status_code = 422


class UnauthorizedError(AppError):
    """Authentication required or failed."""

    code = "UNAUTHORIZED"
    status_code = 401


class ForbiddenError(AppError):
    """Authenticated caller lacks required permissions."""

    code = "FORBIDDEN"
    status_code = 403


class DomainError(AppError):
    """Business rule or domain logic violation (e.g. invalid status transition)."""

    code = "DOMAIN_ERROR"
    status_code = 422


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
