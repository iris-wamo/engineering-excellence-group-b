"""Unit tests for taskflow_shared.logging."""

import logging
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from taskflow_shared.contracts.constants import HEADER_REQUEST_ID
from taskflow_shared.logging import (
    RequestIdFilter,
    RequestIdMiddleware,
    configure_logging,
    get_request_id,
    set_request_id,
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
    """Verify middleware preserves valid incoming X-Request-ID header."""
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


def test_request_id_middleware_sanitizes_invalid_and_overlong() -> None:
    """Verify middleware replaces over-long or invalid incoming IDs with new UUID."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/test-sanitize")
    def endpoint() -> dict[str, str | None]:
        return {"req_id": get_request_id()}

    client = TestClient(app)

    # 1. Over-long header (e.g. 5,000 chars)
    huge_id = "A" * 5000
    resp_huge = client.get("/test-sanitize", headers={HEADER_REQUEST_ID: huge_id})
    assert resp_huge.status_code == 200
    assert resp_huge.headers[HEADER_REQUEST_ID] != huge_id
    assert len(resp_huge.headers[HEADER_REQUEST_ID]) == 32  # generated hex uuid

    # 2. Invalid characters (e.g. carriage return, spaces, special chars)
    invalid_id = "bad\r\ninjection id; DROP TABLE"
    resp_invalid = client.get("/test-sanitize", headers={HEADER_REQUEST_ID: invalid_id})
    assert resp_invalid.status_code == 200
    assert resp_invalid.headers[HEADER_REQUEST_ID] != invalid_id
    assert len(resp_invalid.headers[HEADER_REQUEST_ID]) == 32


def test_request_id_filter_injects_record() -> None:
    """Verify RequestIdFilter attaches request_id to LogRecord."""
    log_filter = RequestIdFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test message",
        args=(),
        exc_info=None,
    )

    # When no request id is set, defaults to "-"
    set_request_id(None)
    log_filter.filter(record)
    assert getattr(record, "request_id", None) == "-"

    # When request id is set, record.request_id is populated
    set_request_id("trace-12345")
    log_filter.filter(record)
    assert getattr(record, "request_id", None) == "trace-12345"


def test_configure_logging() -> None:
    """Verify configure_logging attaches RequestIdFilter to root logger."""
    configure_logging(level=logging.DEBUG)
    root = logging.getLogger()
    assert any(
        any(isinstance(f, RequestIdFilter) for f in handler.filters) for handler in root.handlers
    )
