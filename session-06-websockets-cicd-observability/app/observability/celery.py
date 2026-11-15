"""Completion logs and Prometheus metrics for Celery task runs, and the worker's metrics server.

The signal handlers in app/core/celery_app.py call these. The worker runs tasks in forked
child processes, each with its own copy of the metrics, so the worker uses prometheus_client's
multiprocess mode: children write to files in PROMETHEUS_MULTIPROC_DIR and the main process
serves their sum on worker_metrics_port.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any

from celery.exceptions import Retry
from prometheus_client import CollectorRegistry, multiprocess, start_http_server
from taskflow_shared.logging import (
    bind_log_fields,
    current_log_context,
    error_category,
    get_request_id,
    restore_log_context,
    start_log_context,
)

from app.observability.metrics import CELERY_TASK_DURATION, CELERY_TASKS

logger = logging.getLogger("app.tasks")

# Celery task states mapped to the outcome label
OUTCOMES = {"SUCCESS": "succeeded", "FAILURE": "failed", "RETRY": "retried"}

# Fields of Celery's own "received"/"succeeded" records that hold task arguments and results
TASK_PAYLOAD_FIELDS = ("args", "kwargs", "return_value")
OMITTED = "[omitted]"

# Start times of the runs in progress in this process, by Celery task id
_started: dict[str, float] = {}
# Request id and log fields that were current before each run started. In the worker these
# are empty; a task run in-process (.apply(), eager mode) gets its caller's back afterwards.
_callers: dict[str, tuple[str | None, dict[str, Any] | None]] = {}


def task_started(task_id: str, task_name: str) -> None:
    _callers[task_id] = (get_request_id(), current_log_context())
    start_log_context()
    # celery_task_id, not task_id: on request records task_id is the TaskFlow task
    bind_log_fields(task_name=task_name, celery_task_id=task_id)
    _started[task_id] = time.perf_counter()


def task_errored(exception: BaseException | None) -> None:
    """Record why a run failed or is being retried (called before task_finished)."""
    # task_retry passes Celery's Retry wrapper; the error that caused the retry is in .exc
    if isinstance(exception, Retry) and isinstance(exception.exc, BaseException):
        exception = exception.exc
    if exception is not None:
        bind_log_fields(error_category=error_category(exception))


def task_finished(task_id: str, task_name: str, state: str | None, retries: int) -> str | None:
    """Count and log the run, restore the caller's log fields, and return its request id."""
    started = _started.pop(task_id, None)
    duration = time.perf_counter() - started if started is not None else None
    outcome = OUTCOMES.get(state or "", (state or "unknown").lower())

    CELERY_TASKS.labels(task_name, outcome).inc()
    if duration is not None:
        CELERY_TASK_DURATION.labels(task_name).observe(duration)

    logger.log(
        logging.ERROR if outcome == "failed" else logging.INFO,
        "%s %s",
        task_name,
        outcome,
        extra={
            "operation": task_name,
            "outcome": outcome,
            "retries": retries,
            "duration_ms": round(duration * 1000, 2) if duration is not None else None,
        },
    )
    caller_request_id, caller_fields = _callers.pop(task_id, (None, None))
    restore_log_context(caller_fields)
    return caller_request_id


class TaskPayloadFilter(logging.Filter):
    """Keep task arguments and return values out of Celery's own log records.

    Celery passes them in a `data` dict that is both the record's extra field and the
    message's format arguments ("... succeeded in 0.1s: %(return_value)s"), so both are
    replaced. TaskFlow's tasks take IDs today; this stops a future task's email or token
    from reaching the logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        data = getattr(record, "data", None)
        if isinstance(data, dict) and any(field in data for field in TASK_PAYLOAD_FIELDS):
            cleaned = {**data, **{f: OMITTED for f in TASK_PAYLOAD_FIELDS if f in data}}
            record.data = cleaned
            if record.args is data:
                record.args = cleaned
        return True


def serve_worker_metrics(addr: str, port: int) -> bool:
    """Serve the summed metrics of all worker processes. Call once, in the main process."""
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not multiproc_dir:
        logger.warning(
            "PROMETHEUS_MULTIPROC_DIR is not set, so worker metrics are not served; "
            "metrics recorded in the pool's child processes would not be visible"
        )
        return False

    directory = Path(multiproc_dir)
    directory.mkdir(parents=True, exist_ok=True)
    # Files left by a previous run of this worker would be added to this run's counts. The
    # directory must belong to this worker alone (Compose: its own container; make target:
    # a fresh temporary directory).
    for stale in directory.glob("*.db"):
        stale.unlink()

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=multiproc_dir)  # type: ignore[no-untyped-call]
    start_http_server(port, addr=addr, registry=registry)
    logger.info("Serving worker metrics on %s:%s", addr, port)
    return True
