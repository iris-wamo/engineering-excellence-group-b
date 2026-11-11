"""Logging filters and formatters for structured request tracing."""

import logging

from taskflow_shared.logging.context import get_request_id


class RequestIdFilter(logging.Filter):
    """Injects request_id into standard logging.LogRecord instances."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"  # type: ignore[attr-defined]
        return True


def configure_logging(
    level: int = logging.INFO,
    log_format: str = "[%(asctime)s] [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
) -> None:
    """Configure logging with RequestIdFilter on the root logger."""
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(log_format))
    root.handlers = [handler]
