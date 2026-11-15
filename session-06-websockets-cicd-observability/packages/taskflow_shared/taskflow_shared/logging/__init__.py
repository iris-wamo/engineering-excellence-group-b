"""Request tracing and structured logging helpers."""

from taskflow_shared.logging.context import (
    bind_log_fields,
    clear_log_context,
    current_log_context,
    get_log_fields,
    get_request_id,
    restore_log_context,
    set_request_id,
    start_log_context,
)
from taskflow_shared.logging.exceptions import already_logged, error_category, mark_logged
from taskflow_shared.logging.formatters import (
    JsonFormatter,
    RedactingFormatter,
    RequestIdFilter,
    configure_logging,
    redact,
)
from taskflow_shared.logging.middleware import RequestIdMiddleware

__all__ = [
    "get_request_id",
    "set_request_id",
    "start_log_context",
    "clear_log_context",
    "bind_log_fields",
    "get_log_fields",
    "current_log_context",
    "restore_log_context",
    "error_category",
    "mark_logged",
    "already_logged",
    "RedactingFormatter",
    "RequestIdMiddleware",
    "RequestIdFilter",
    "JsonFormatter",
    "configure_logging",
    "redact",
]
