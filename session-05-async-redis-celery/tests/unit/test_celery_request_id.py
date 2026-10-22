"""Unit tests for carrying the API request id into Celery jobs and their logs."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from taskflow_shared.logging import get_request_id, set_request_id

from app.core.celery_app import (
    REQUEST_ID_HEADER,
    _add_request_id_filter,
    _attach_request_id,
    _clear_request_id,
    _restore_request_id,
)


@pytest.fixture(autouse=True)
def _reset_request_id() -> Any:
    set_request_id(None)
    yield
    set_request_id(None)


@pytest.mark.unit
def test_publish_copies_the_current_request_id_into_the_headers() -> None:
    set_request_id("req-123")
    headers: dict[str, Any] = {}

    _attach_request_id(headers=headers)

    assert headers[REQUEST_ID_HEADER] == "req-123"


@pytest.mark.unit
def test_publish_outside_a_request_adds_no_header() -> None:
    headers: dict[str, Any] = {}

    _attach_request_id(headers=headers)

    assert REQUEST_ID_HEADER not in headers


@pytest.mark.unit
def test_worker_restores_the_request_id_for_the_job_and_clears_it_after() -> None:
    task: Any = SimpleNamespace(request=SimpleNamespace(**{REQUEST_ID_HEADER: "req-123"}))

    _restore_request_id(task=task)
    assert get_request_id() == "req-123"

    _clear_request_id()
    assert get_request_id() is None


@pytest.mark.unit
def test_scheduled_job_without_a_request_id_runs_with_none() -> None:
    set_request_id("left-over")
    task: Any = SimpleNamespace(request=SimpleNamespace())

    _restore_request_id(task=task)

    assert get_request_id() is None


@pytest.mark.unit
def test_worker_log_handlers_get_the_request_id_filter() -> None:
    logger = logging.getLogger("test-celery-request-id")
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    try:
        _add_request_id_filter(logger=logger)
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
        set_request_id("req-123")
        assert handler.filter(record)
        assert record.request_id == "req-123"  # type: ignore[attr-defined]
    finally:
        logger.removeHandler(handler)
