"""TaskFlow Shared Backend Package.

Provides reusable components across TaskFlow modules:
- config: Base settings and environment abstractions
- concurrency: Run coroutines from synchronous code
- errors: AppError hierarchy, schemas, FastAPI exception handlers, and retry classification
- locks: Redis distributed lock with token-checked release and renewal
- pagination: Generic PaginatedResponse and PaginationParams
- logging: Request ID context and tracing middleware
- contracts: Common schema interfaces and header constants
- enums: Common runtime enums
"""

from taskflow_shared.concurrency import run_async
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
    PermanentError,
    TransientError,
    UnauthorizedError,
    ValidationAppError,
    register_exception_handlers,
)
from taskflow_shared.locks import (
    acquire_redis_lock,
    distributed_lock,
    release_redis_lock,
    renew_redis_lock,
)
from taskflow_shared.logging import (
    RequestIdFilter,
    RequestIdMiddleware,
    configure_logging,
    get_request_id,
    set_request_id,
)
from taskflow_shared.pagination import PaginatedResponse, PaginationParams

__version__ = "0.1.0"

__all__ = [
    # Concurrency
    "run_async",
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
    "ErrorDetail",
    "ErrorBody",
    "ErrorResponse",
    "register_exception_handlers",
    "TransientError",
    "PermanentError",
    # Locks
    "acquire_redis_lock",
    "release_redis_lock",
    "renew_redis_lock",
    "distributed_lock",
    # Logging
    "get_request_id",
    "set_request_id",
    "RequestIdMiddleware",
    "RequestIdFilter",
    "configure_logging",
    # Pagination
    "PaginatedResponse",
    "PaginationParams",
]
