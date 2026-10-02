"""Logging filters and formatters for structured request tracing."""

import logging

from taskflow_shared.logging.context import get_request_id


class RequestIdFilter(logging.Filter):
    """Injects request_id into standard logging.LogRecord instances."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"  # type: ignore[attr-defined]
        return True
