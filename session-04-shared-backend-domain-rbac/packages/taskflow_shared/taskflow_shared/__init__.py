"""TaskFlow Shared Backend Package.

Provides reusable components across TaskFlow modules:
- config: Base settings and environment abstractions
- errors: AppError hierarchy, schemas, and FastAPI exception handlers
- pagination: Generic PaginatedResponse and PaginationParams
- logging: Request ID context and tracing middleware
- contracts: Common schema interfaces and header constants
- enums: Common runtime enums
"""

from taskflow_shared.config import BaseAppSettings
from taskflow_shared.contracts import (
    HEADER_CORRELATION_ID,
    HEADER_REQUEST_ID,
    HEADER_WORKSPACE_ID,
    BaseSchema,
    TimestampedSchema,
)
from taskflow_shared.enums import Environment, SortOrder
from taskflow_shared.errors import (
    AppError,
    ConflictError,
    DomainError,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    ProjectMembershipRequiredError,
    TransactionSimulationError,
    UnauthorizedError,
    ValidationAppError,
    register_exception_handlers,
)
from taskflow_shared.logging import (
    RequestIdFilter,
    RequestIdMiddleware,
    get_request_id,
    set_request_id,
)
from taskflow_shared.pagination import PaginatedResponse, PaginationParams

__version__ = "0.1.0"

__all__ = [
    # Config
    "BaseAppSettings",
    # Contracts
    "BaseSchema",
    "TimestampedSchema",
    "HEADER_REQUEST_ID",
    "HEADER_WORKSPACE_ID",
    "HEADER_CORRELATION_ID",
    # Enums
    "Environment",
    "SortOrder",
    # Errors
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
    # Logging
    "get_request_id",
    "set_request_id",
    "RequestIdMiddleware",
    "RequestIdFilter",
    # Pagination
    "PaginatedResponse",
    "PaginationParams",
]
