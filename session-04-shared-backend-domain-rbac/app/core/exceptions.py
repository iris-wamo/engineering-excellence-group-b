"""Application errors, error response schemas, and FastAPI exception handlers.

Re-exports unified error foundations and domain exceptions from taskflow_shared.
"""

from __future__ import annotations

from taskflow_shared.errors import (
    AppError,
    ConflictError,
    DomainError,
    EmailAlreadyExistsError,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    ProjectMembershipRequiredError,
    TransactionSimulationError,
    UnauthorizedError,
    UserNotFoundError,
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
    "EmailAlreadyExistsError",
    "UserNotFoundError",
    "ProjectMembershipRequiredError",
    "TransactionSimulationError",
    "ErrorDetail",
    "ErrorBody",
    "ErrorResponse",
    "register_exception_handlers",
]
