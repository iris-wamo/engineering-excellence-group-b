"""Unified error handling and response envelopes."""

from taskflow_shared.errors.exceptions import (
    AppError,
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    ProjectMembershipRequiredError,
    TransactionSimulationError,
    UnauthorizedError,
    ValidationAppError,
)
from taskflow_shared.errors.handlers import register_exception_handlers
from taskflow_shared.errors.schemas import ErrorBody, ErrorDetail, ErrorResponse

__all__ = [
    "AppError",
    "NotFoundError",
    "ConflictError",
    "ValidationAppError",
    "UnauthorizedError",
    "ForbiddenError",
    "DomainError",
    "ProjectMembershipRequiredError",
    "TransactionSimulationError",
    "ErrorDetail",
    "ErrorBody",
    "ErrorResponse",
    "register_exception_handlers",
]
