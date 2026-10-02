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


class ProjectMembershipRequiredError(AppError):
    """Action requires project membership."""

    code = "MEMBERSHIP_REQUIRED"
    status_code = 403


class TransactionSimulationError(AppError):
    """Simulated failure during transactional testing."""

    code = "TRANSACTION_SIMULATION_ERROR"
    status_code = 500
