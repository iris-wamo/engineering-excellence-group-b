"""ASGI middleware that writes one log record and one set of metrics per HTTP request."""

import logging
import re
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from taskflow_shared.logging import (
    bind_log_fields,
    clear_log_context,
    error_category,
    mark_logged,
    start_log_context,
)
from taskflow_shared.observability.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS,
    UNMATCHED_ROUTE,
    method_label,
)

logger = logging.getLogger("app.requests")

# Path parameters worth putting on the request's log record
LOGGED_PATH_PARAMS = ("project_id", "task_id")

# "{item_id:int}" -> "{item_id}", so the label matches the route as written
_CONVERTOR = re.compile(r"\{(\w+):[^}]+\}")


def route_template(scope: Scope) -> str:
    """The matched route's full path template, e.g. /api/v1/tasks/{task_id}.

    FastAPI keeps included routers nested, so the matched route only knows its path inside
    its own router (/tasks/{task_id}). The full path is on FastAPI's effective route context,
    a private scope entry; if a FastAPI upgrade drops it, the label falls back to the route's
    own path. Plain routes (/docs, /metrics) have neither and are found by their endpoint.
    """
    context = (scope.get("fastapi") or {}).get("effective_route_context")
    path = getattr(context, "path", None) or getattr(
        scope.get("route") or _top_level_route(scope), "path_format", None
    )
    return _CONVERTOR.sub(r"{\1}", path) if isinstance(path, str) and path else UNMATCHED_ROUTE


def _top_level_route(scope: Scope) -> Any:
    endpoint = scope.get("endpoint")
    if endpoint is None:
        return None
    for candidate in getattr(scope.get("app"), "routes", ()):
        if getattr(candidate, "endpoint", None) is endpoint:
            return candidate
    return None


def _id_value(raw: Any) -> Any:
    """Path params arrive as strings; log numeric IDs as numbers, like user_id."""
    return int(raw) if isinstance(raw, str) and raw.isdigit() else raw


def outcome_for(status_code: int) -> str:
    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    return "success"


class ObservabilityMiddleware:
    """Times each request, records its metrics, and logs it with the fields bound on the way.

    A pure ASGI middleware rather than BaseHTTPMiddleware so it sees the matched route in the
    scope after the app runs, and records unhandled exceptions before re-raising them.
    """

    def __init__(self, app: ASGIApp, skip_paths: frozenset[str] = frozenset({"/metrics"})):
        self.app = app
        self.skip_paths = skip_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.skip_paths:
            await self.app(scope, receive, send)
            return

        start_log_context()
        status_code: int | None = None
        error: Exception | None = None
        started = time.perf_counter()

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        except Exception as exc:
            error = exc
            bind_log_fields(error_category=error_category(exc))
            # The traceback goes on this record, with the request's fields; the outer
            # catch-all handler sees the mark and does not log it again.
            mark_logged(exc)
            raise
        finally:
            # A failure after the response started keeps the status the client received
            self._record(scope, status_code or 500, time.perf_counter() - started, error)
            clear_log_context()

    def _record(
        self, scope: Scope, status_code: int, duration: float, error: Exception | None
    ) -> None:
        method = method_label(scope["method"])
        route = route_template(scope)
        HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
        HTTP_REQUEST_DURATION.labels(method, route).observe(duration)

        path_params: dict[str, Any] = scope.get("path_params") or {}
        bind_log_fields(**{name: _id_value(path_params.get(name)) for name in LOGGED_PATH_PARAMS})
        outcome = "server_error" if error is not None else outcome_for(status_code)
        logger.log(
            logging.ERROR if outcome == "server_error" else logging.INFO,
            "%s %s %s",
            method,
            route,
            status_code,
            exc_info=error,
            extra={
                "operation": f"{method} {route}",
                "outcome": outcome,
                "status": status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
