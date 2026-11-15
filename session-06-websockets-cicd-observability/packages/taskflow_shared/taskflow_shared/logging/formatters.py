"""Logging filters and formatters for structured request tracing."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from taskflow_shared.logging.context import get_log_fields, get_request_id

REDACTED = "[REDACTED]"

# Field names whose values never reach the logs, matched case-insensitively and as substrings
# ("access_token", "X-Api-Key", "new_password" all match).
SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
    "credential",
)

# Credentials that can end up inside a free-text message: bearer headers and JWTs.
_SENSITIVE_TEXT = re.compile(
    r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"
)

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_STANDARD_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()
) | {"message", "asctime", "request_id"}


def is_sensitive_key(key: str) -> bool:
    # Header-style names use hyphens ("X-Api-Key"); compare them like snake_case
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:
    """Replace the values of sensitive keys, recursively, and mask credentials in strings."""
    if isinstance(value, dict):
        return {
            key: REDACTED if is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    return _SENSITIVE_TEXT.sub(REDACTED, text)


class RequestIdFilter(logging.Filter):
    """Injects request_id into standard logging.LogRecord instances."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request id and bound fields.

    Fields come from bind_log_fields (the current request or job) and from `extra=` on the
    logging call; `extra=` wins on a clash. Sensitive keys and credentials are redacted.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        entry.update(get_log_fields())
        entry.update(
            {
                key: value
                for key, value in vars(record).items()
                if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_")
            }
        )
        if record.exc_info and record.exc_info[0] is not None:
            entry["exc_type"] = record.exc_info[0].__name__
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(redact(entry), default=str)


def configure_logging(
    level: int | str = logging.INFO,
    log_format: str = "[%(asctime)s] [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
    style: Literal["json", "text"] = "text",
) -> None:
    """Configure the root logger: JSON lines, or the text format above, with request ids.

    Uvicorn's own loggers are routed through the root handler so every line has one format,
    and its access log is turned off because the app writes its own request records.
    """
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if style == "json" else logging.Formatter(log_format))
    root.handlers = [handler]

    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
