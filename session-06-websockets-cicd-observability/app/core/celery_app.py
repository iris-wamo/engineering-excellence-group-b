"""Celery application and configuration for TaskFlow background jobs."""

import logging
from typing import Any

from celery import Celery, Task
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    before_task_publish,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_init,
    worker_process_init,
)
from taskflow_shared.logging import (
    JsonFormatter,
    RedactingFormatter,
    RequestIdFilter,
    get_request_id,
    set_request_id,
)

from app.core.config import settings
from app.observability import celery as task_observability
from app.observability.tracing import instrument_worker

# Message header that carries the API request's X-Request-ID to the worker
REQUEST_ID_HEADER = "request_id"

celery_app = Celery(
    "taskflow",
    broker=str(settings.celery_broker_url),
    backend=str(settings.celery_result_backend),
    include=[
        "app.tasks.notification_tasks",
        "app.tasks.reminder_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Fail fast when Redis is slow or unreachable instead of blocking the publisher
    # (redis-py's default socket_connect_timeout is None).
    broker_connection_timeout=1,
    broker_transport_options={"socket_connect_timeout": 1, "socket_timeout": 1},
    # Worker and Beat log lines carry the request id of the API call that queued the job
    # ("-" for scheduled jobs); the filter that fills it in is attached below.
    worker_log_format="[%(asctime)s: %(levelname)s/%(processName)s] [%(request_id)s] %(message)s",
    worker_task_log_format=(
        "[%(asctime)s: %(levelname)s/%(processName)s] [%(request_id)s] "
        "%(task_name)s[%(task_id)s]: %(message)s"
    ),
    beat_schedule={
        "requeue-stale-assignment-notifications": {
            "task": "app.tasks.notification_tasks.requeue_stale_assignment_notifications",
            "schedule": settings.notification_requeue_interval_seconds,
        },
        "send-due-task-reminders-periodic": {
            "task": "app.tasks.reminder_tasks.send_due_task_reminders",
            "schedule": settings.due_reminder_interval_seconds,
        },
    },
)


@before_task_publish.connect
def _attach_request_id(headers: dict[str, Any] | None = None, **_: Any) -> None:
    """Copy the current request id (set by RequestIdMiddleware) into the job's headers."""
    request_id = get_request_id()
    if headers is not None and request_id:
        headers.setdefault(REQUEST_ID_HEADER, request_id)


@task_prerun.connect
def _restore_request_id(task_id: str | None = None, task: Task | None = None, **_: Any) -> None:
    """Make the queuing request's id the current request id while the job runs."""
    if task_id and task:
        task_observability.task_started(task_id, task.name)
    set_request_id(getattr(task.request, REQUEST_ID_HEADER, None) if task else None)


@task_failure.connect
@task_retry.connect
def _record_task_error(
    exception: BaseException | None = None, reason: BaseException | None = None, **_: Any
) -> None:
    """task_failure passes the error as `exception`, task_retry as `reason`."""
    task_observability.task_errored(exception or reason)


@task_postrun.connect
def _clear_request_id(
    task_id: str | None = None,
    task: Task | None = None,
    state: str | None = None,
    **_: Any,
) -> None:
    """Log and count the finished run while its request id is still set, then put back the
    caller's (none in the worker; the calling request's when run in-process)."""
    caller_request_id = None
    if task_id and task:
        caller_request_id = task_observability.task_finished(
            task_id, task.name, state, task.request.retries or 0
        )
    set_request_id(caller_request_id)


@worker_process_init.connect
def _trace_pool_process(**_: Any) -> None:
    instrument_worker()


@worker_init.connect
def _serve_worker_metrics(**_: Any) -> None:
    task_observability.serve_worker_metrics(
        settings.worker_metrics_addr, settings.worker_metrics_port
    )


@after_setup_logger.connect
@after_setup_task_logger.connect
def _add_request_id_filter(logger: logging.Logger, **_: Any) -> None:
    """Fill %(request_id)s in the worker and Beat log formats above, or log JSON lines.

    Either way, task arguments are dropped and credentials are masked.
    """
    for handler in logger.handlers:
        handler.addFilter(RequestIdFilter())
        handler.addFilter(task_observability.TaskPayloadFilter())
        if settings.log_format == "json":
            handler.setFormatter(JsonFormatter())
        elif handler.formatter is not None:
            handler.setFormatter(RedactingFormatter(handler.formatter))


celery_app.set_default()
