"""Unit tests for taskflow_shared.logging."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from taskflow_shared.contracts.constants import HEADER_REQUEST_ID
from taskflow_shared.logging import (
    RequestIdMiddleware,
    get_request_id,
)


def test_request_id_middleware_generated() -> None:
    """Verify middleware generates request ID when not provided."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    captured_id: str | None = None

    @app.get("/test-id")
    def endpoint() -> dict[str, bool]:
        nonlocal captured_id
        captured_id = get_request_id()
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/test-id")

    assert response.status_code == 200
    assert HEADER_REQUEST_ID in response.headers
    response_header_id = response.headers[HEADER_REQUEST_ID]
    assert captured_id == response_header_id
    assert len(response_header_id) > 0


def test_request_id_middleware_propagated() -> None:
    """Verify middleware preserves incoming X-Request-ID header."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    custom_id = f"custom-req-{uuid.uuid4().hex[:8]}"

    @app.get("/test-custom-id")
    def endpoint() -> dict[str, str | None]:
        return {"req_id": get_request_id()}

    client = TestClient(app)
    response = client.get("/test-custom-id", headers={HEADER_REQUEST_ID: custom_id})

    assert response.status_code == 200
    assert response.headers[HEADER_REQUEST_ID] == custom_id
    assert response.json()["req_id"] == custom_id
