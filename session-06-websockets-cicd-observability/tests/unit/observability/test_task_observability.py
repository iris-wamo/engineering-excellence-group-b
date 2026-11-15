"""Unit tests for Celery task run metrics, completion logs and the worker metrics server."""

import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from celery.exceptions import Retry
from prometheus_client import REGISTRY
from taskflow_shared.logging import JsonFormatter, get_log_fields, set_request_id

from app.core.celery_app import _clear_request_id, _record_task_error, _restore_request_id
from app.observability import celery as task_observability

TASK = "app.tasks.notification_tasks.send_assignment_notification"


class JsonLines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(JsonFormatter().format(record)))


@pytest.fixture()
def task_logs() -> Iterator[JsonLines]:
    handler = JsonLines()
    logger = logging.getLogger("app.tasks")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    set_request_id(None)


def _task(retries: int = 0, request_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        name=TASK, request=SimpleNamespace(retries=retries, request_id=request_id)
    )


def _runs(outcome: str) -> float:
    labels = {"task": TASK, "outcome": outcome}
    return REGISTRY.get_sample_value("taskflow_celery_tasks_total", labels) or 0.0


def _durations() -> float:
    return (
        REGISTRY.get_sample_value("taskflow_celery_task_duration_seconds_count", {"task": TASK})
        or 0.0
    )


def _run(state: str, error: BaseException | None = None, retries: int = 0) -> None:
    """Fire the worker's signal handlers in the order Celery does for one run."""
    task = _task(retries=retries, request_id="req-9")
    _restore_request_id(task_id="t-1", task=task)  # type: ignore[arg-type]
    if error is not None:
        _record_task_error(exception=error)
    _clear_request_id(task_id="t-1", task=task, state=state)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("state", "outcome"),
    [("SUCCESS", "succeeded"), ("FAILURE", "failed"), ("RETRY", "retried")],
)
def test_each_run_is_counted_by_outcome_and_timed(state: str, outcome: str) -> None:
    before_runs, before_durations = _runs(outcome), _durations()

    _run(state)

    assert _runs(outcome) == before_runs + 1
    assert _durations() == before_durations + 1


def test_completion_log_carries_the_queuing_request_id_and_task_fields(
    task_logs: JsonLines,
) -> None:
    _run("SUCCESS", retries=2)

    [entry] = task_logs.entries
    assert entry["request_id"] == "req-9"
    assert entry["operation"] == TASK
    assert entry["task_name"] == TASK
    assert entry["celery_task_id"] == "t-1"
    assert "task_id" not in entry
    assert entry["outcome"] == "succeeded"
    assert entry["retries"] == 2
    assert entry["duration_ms"] >= 0
    assert entry["level"] == "INFO"


def test_failure_log_names_the_error_category(task_logs: JsonLines) -> None:
    _run("FAILURE", error=ConnectionError("redis down"))

    [entry] = task_logs.entries
    assert entry["outcome"] == "failed"
    assert entry["error_category"] == "ConnectionError"
    assert entry["level"] == "ERROR"


def test_retry_reason_is_recorded_as_the_error_category(task_logs: JsonLines) -> None:
    task = _task()
    _restore_request_id(task_id="t-2", task=task)  # type: ignore[arg-type]
    _record_task_error(reason=Retry(exc=TimeoutError("slow")))
    _clear_request_id(task_id="t-2", task=task, state="RETRY")  # type: ignore[arg-type]

    [entry] = task_logs.entries
    assert entry["outcome"] == "retried"
    assert entry["error_category"] == "TimeoutError"


def test_log_fields_do_not_leak_into_the_next_run(task_logs: JsonLines) -> None:
    _run("FAILURE", error=ValueError("bad"))

    assert get_log_fields() == {}


def test_worker_metrics_are_not_served_without_a_multiprocess_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    started: list[int] = []
    monkeypatch.setattr(
        task_observability, "start_http_server", lambda port, **_: started.append(port)
    )

    assert task_observability.serve_worker_metrics(9808) is False
    assert started == []


def test_worker_metrics_server_clears_stale_files_and_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    (tmp_path / "counter_123.db").write_bytes(b"stale")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    started: list[int] = []
    monkeypatch.setattr(
        task_observability, "start_http_server", lambda port, **_: started.append(port)
    )

    assert task_observability.serve_worker_metrics(9808) is True
    assert started == [9808]
    assert list(tmp_path.glob("*.db")) == []
