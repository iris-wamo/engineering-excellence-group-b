"""Celery application and configuration for TaskFlow background jobs."""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "taskflow",
    broker=str(settings.celery_broker_url),
    backend=str(settings.celery_result_backend),
    include=["app.tasks.notification_tasks"],
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
)

celery_app.set_default()
