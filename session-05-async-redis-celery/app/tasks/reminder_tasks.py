"""Celery Beat periodic task for due-task reminders with overlap prevention."""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import redis.asyncio as aioredis
from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.config import settings
from app.models.enums import TaskStatus
from app.models.notification import Notification
from app.models.task import Task as TaskModel
from app.tasks.db import get_worker_db, run_async
from app.tasks.locks import distributed_lock

logger = logging.getLogger(__name__)

REMINDER_LOCK_KEY = "taskflow:locks:send_due_task_reminders"


async def _execute_due_task_reminders(
    db: AsyncSession,
    threshold_days: int = 1,
    dedup_window_hours: int = 24,
    overdue_cutoff_days: int = 14,
) -> dict[str, Any]:
    """Inspect tasks close to their due date and stage reminder notifications.

    Filters for incomplete tasks assigned to a user whose due date is on or before
    the threshold. Uses batch querying to prevent N+1 database lookups and ensures
    assignees receive at most one reminder within the deduplication window.
    """
    today = date.today()
    max_due = today + timedelta(days=threshold_days)
    min_due = today - timedelta(days=overdue_cutoff_days)

    stmt = (
        select(TaskModel)
        .where(
            TaskModel.due_date.is_not(None),
            TaskModel.assignee_id.is_not(None),
            TaskModel.status != TaskStatus.done,
            TaskModel.due_date >= min_due,
            TaskModel.due_date <= max_due,
        )
        .order_by(TaskModel.due_date.asc(), TaskModel.id.asc())
    )
    tasks = (await db.scalars(stmt)).all()

    reminders_created = 0
    reminders_skipped = 0
    reminded_task_ids: list[int] = []

    cutoff = datetime.now(UTC) - timedelta(hours=dedup_window_hours)

    # Batch-fetch all task IDs that were already reminded in the deduplication window
    candidate_task_ids = [t.id for t in tasks]
    already_reminded_task_ids: set[int] = set()
    if candidate_task_ids:
        existing_notifs = (
            await db.scalars(
                select(Notification.task_id).where(
                    Notification.task_id.in_(candidate_task_ids),
                    Notification.type == "TASK_DUE_REMINDER",
                    Notification.created_at >= cutoff,
                )
            )
        ).all()
        already_reminded_task_ids = {nid for nid in existing_notifs if nid is not None}

    for task in tasks:
        assert task.assignee_id is not None  # Guaranteed by query filter

        if task.id in already_reminded_task_ids:
            reminders_skipped += 1
            logger.debug(
                "Skipping reminder for task %s (recipient %s): already sent in dedup window",
                task.id,
                task.assignee_id,
            )
            continue

        notification = Notification(
            recipient_id=task.assignee_id,
            task_id=task.id,
            type="TASK_DUE_REMINDER",
            status="sent",
            payload={
                "task_id": task.id,
                "task_title": task.title,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "is_overdue": task.due_date < today if task.due_date else False,
                "priority": task.priority.value,
                "status": task.status.value,
                "workspace_id": task.workspace_id,
                "project_id": task.project_id,
            },
        )
        db.add(notification)
        reminders_created += 1
        reminded_task_ids.append(task.id)

    if reminders_created > 0:
        await db.commit()

    return {
        "status": "success",
        "tasks_checked": len(tasks),
        "reminders_created": reminders_created,
        "reminders_skipped": reminders_skipped,
        "reminded_task_ids": reminded_task_ids,
    }


async def _process_due_task_reminders(
    threshold_days: int | None = None,
    dedup_window_hours: int = 24,
    db: AsyncSession | None = None,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any]:
    """Execute the due task reminder sweep wrapped in a Redis distributed lock."""
    target_threshold = (
        threshold_days if threshold_days is not None else settings.due_reminder_window_days
    )

    async with distributed_lock(
        REMINDER_LOCK_KEY, timeout_seconds=300, redis_client=redis_client
    ) as token:
        if token is None:
            logger.warning(
                "Another due-task reminder sweep is currently in progress. "
                "Skipping overlapping run."
            )
            return {
                "status": "skipped",
                "reason": "overlapping_run",
                "reminders_created": 0,
                "reminders_skipped": 0,
            }

        if db is not None:
            return await _execute_due_task_reminders(
                db, threshold_days=target_threshold, dedup_window_hours=dedup_window_hours
            )

        async with get_worker_db() as worker_db:
            return await _execute_due_task_reminders(
                worker_db,
                threshold_days=target_threshold,
                dedup_window_hours=dedup_window_hours,
            )


@celery_app.task(
    bind=True,
    name="app.tasks.reminder_tasks.send_due_task_reminders",
    max_retries=2,
)
def send_due_task_reminders(
    self: Task,
    threshold_days: int | None = None,
    dedup_window_hours: int = 24,
) -> dict[str, Any]:
    """Celery Beat periodic task entrypoint for due-task reminders.

    Prevents overlapping executions via Redis distributed lock and deduplicates
    reminders within the specified window.
    """
    logger.info("Executing scheduled due-task reminder sweep.")
    try:
        return run_async(
            _process_due_task_reminders(
                threshold_days=threshold_days,
                dedup_window_hours=dedup_window_hours,
            )
        )
    except Exception as exc:
        logger.exception("Error executing due-task reminders sweep: %s", exc)
        raise self.retry(exc=exc, countdown=10) from exc
