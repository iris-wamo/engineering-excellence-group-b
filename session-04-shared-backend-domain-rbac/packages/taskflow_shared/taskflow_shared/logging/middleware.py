"""Middleware for tracing request IDs across inbound requests and outbound responses."""

import re
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from taskflow_shared.contracts.constants import HEADER_REQUEST_ID
from taskflow_shared.logging.context import set_request_id

VALID_REQUEST_ID_REGEX = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_REQUEST_ID_LENGTH = 128


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Captures or generates an X-Request-ID and injects it into context and response."""

    @classmethod
    def sanitize_request_id(cls, raw_id: str | None) -> str:
        """Validate and sanitize an incoming request ID, or generate a fresh UUID."""
        if raw_id:
            stripped = raw_id.strip()
            if (
                1 <= len(stripped) <= MAX_REQUEST_ID_LENGTH
                and VALID_REQUEST_ID_REGEX.match(stripped) is not None
            ):
                return stripped
        return uuid.uuid4().hex

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming_id = request.headers.get(HEADER_REQUEST_ID)
        request_id = self.sanitize_request_id(incoming_id)
        set_request_id(request_id)

        response = await call_next(request)
        response.headers[HEADER_REQUEST_ID] = request_id
        return response
