"""Middleware for tracing request IDs across inbound requests and outbound responses."""

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from taskflow_shared.contracts.constants import HEADER_REQUEST_ID
from taskflow_shared.logging.context import set_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Captures or generates an X-Request-ID and injects it into context and response."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming_id = request.headers.get(HEADER_REQUEST_ID)
        request_id = (
            incoming_id.strip() if incoming_id and incoming_id.strip() else uuid.uuid4().hex
        )
        set_request_id(request_id)

        response = await call_next(request)
        response.headers[HEADER_REQUEST_ID] = request_id
        return response
