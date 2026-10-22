"""Service-level unit tests for simulated external service calls (pure, fast, no DB/HTTP)."""

import time

import pytest

from app.core.exceptions import ExternalServiceTimeoutError
from app.schemas.task import ExternalServiceResult
from app.services.task_service import (
    _simulate_external_call_async,
    _simulate_external_call_blocking,
)


async def test_simulate_external_call_async_success() -> None:
    """Async simulator returns ExternalServiceResult with mode='async' and latency_ms >= 0."""
    res = await _simulate_external_call_async(delay=0.01, timeout=1.0)
    assert isinstance(res, ExternalServiceResult)
    assert res.mode == "async"
    assert res.latency_ms >= 0.0
    assert res.status == "healthy"
    assert res.service == "workload_service"


async def test_simulate_external_call_async_timeout() -> None:
    """Async simulator raises ExternalServiceTimeoutError when delay > timeout."""
    with pytest.raises(ExternalServiceTimeoutError) as exc_info:
        await _simulate_external_call_async(delay=0.1, timeout=0.01)
    assert exc_info.value.status_code == 504
    assert exc_info.value.code == "EXTERNAL_SERVICE_TIMEOUT"


def test_simulate_external_call_blocking_success() -> None:
    """Blocking simulator returns ExternalServiceResult with mode='blocking'."""
    res = _simulate_external_call_blocking(delay=0.01, timeout=1.0)
    assert isinstance(res, ExternalServiceResult)
    assert res.mode == "blocking"
    assert res.latency_ms >= 0.0
    assert res.status == "healthy"
    assert res.service == "workload_service"


def test_simulate_external_call_blocking_timeout() -> None:
    """Blocking simulator raises ExternalServiceTimeoutError when delay > timeout."""
    with pytest.raises(ExternalServiceTimeoutError) as exc_info:
        _simulate_external_call_blocking(delay=0.1, timeout=0.01)
    assert exc_info.value.status_code == 504
    assert exc_info.value.code == "EXTERNAL_SERVICE_TIMEOUT"


def test_simulate_external_call_blocking_timeout_timing() -> None:
    """Blocking timeout path raises in roughly timeout seconds."""
    timeout = 0.05
    start = time.perf_counter()
    with pytest.raises(ExternalServiceTimeoutError):
        _simulate_external_call_blocking(delay=0.2, timeout=timeout)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.9 * timeout
    assert elapsed < timeout + 0.5
