"""Celery application and configuration for TaskFlow background jobs."""

import logging
from typing import Any

from celery import Celery, Task
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    before_task_publish,
    task_postrun,
    task_prerun,
)
from taskflow_shared.logging import RequestIdFilter, get_request_id, set_request_id

from app.core.config import settings

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
def _restore_request_id(task: Task | None = None, **_: Any) -> None:
    """Make the queuing request's id the current request id while the job runs."""
    set_request_id(getattr(task.request, REQUEST_ID_HEADER, None) if task else None)


@task_postrun.connect
def _clear_request_id(**_: Any) -> None:
    set_request_id(None)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _add_request_id_filter(logger: logging.Logger, **_: Any) -> None:
    """Fill %(request_id)s in the worker and Beat log formats above."""
    for handler in logger.handlers:
        handler.addFilter(RequestIdFilter())


celery_app.set_default()
