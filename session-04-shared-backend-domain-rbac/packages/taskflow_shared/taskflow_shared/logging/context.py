"""Context variables for request tracing and correlation."""

from contextvars import ContextVar

_request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Retrieve current request ID from context."""
    return _request_id_ctx_var.get()


def set_request_id(request_id: str | None) -> None:
    """Set current request ID in context."""
    _request_id_ctx_var.set(request_id)
