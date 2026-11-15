"""Context variables for request tracing and correlation."""

from contextvars import ContextVar
from typing import Any

_request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Fields added to every log record of the current request or job (user_id, workspace_id, ...).
# The dict is created once per request and mutated in place by bind_log_fields, so fields bound
# deep in a dependency or handler are still visible to the middleware that writes the final
# record, even across the task and thread boundaries that copy the context.
_log_fields_ctx_var: ContextVar[dict[str, Any] | None] = ContextVar("log_fields", default=None)


def get_request_id() -> str | None:
    """Retrieve current request ID from context."""
    return _request_id_ctx_var.get()


def set_request_id(request_id: str | None) -> None:
    """Set current request ID in context."""
    _request_id_ctx_var.set(request_id)


def start_log_context() -> dict[str, Any]:
    """Start an empty set of log fields for a new request or job and return it."""
    fields: dict[str, Any] = {}
    _log_fields_ctx_var.set(fields)
    return fields


def clear_log_context() -> None:
    """Drop the current request's or job's log fields."""
    _log_fields_ctx_var.set(None)


def bind_log_fields(**fields: Any) -> None:
    """Add fields to the current request's or job's log records. No-op outside one."""
    current = _log_fields_ctx_var.get()
    if current is not None:
        current.update({key: value for key, value in fields.items() if value is not None})


def get_log_fields() -> dict[str, Any]:
    """Return a copy of the fields bound to the current request or job."""
    current = _log_fields_ctx_var.get()
    return dict(current) if current else {}
