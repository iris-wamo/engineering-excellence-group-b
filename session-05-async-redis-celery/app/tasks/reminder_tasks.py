"""Celery Beat periodic task for due-task reminders with overlap prevention."""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.concurrency import run_async
from taskflow_shared.locks import distributed_lock

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.redis import create_redis_client
from app.models.enums import TaskStatus
from app.models.notification import Notification
from app.models.task import Task as TaskModel
from app.tasks.db import get_worker_db

logger = logging.getLogger(__name__)

REMINDER_LOCK_KEY = "taskflow:locks:send_due_task_reminders"


def _reminder_for(task: TaskModel, recipient_id: int, today: date) -> Notification:
    return Notification(
        recipient_id=recipient_id,
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


async def _execute_due_task_reminders(
    db: AsyncSession,
    threshold_days: int = 1,
    dedup_window_hours: int = 24,
    overdue_cutoff_days: int = 14,
    batch_size: int = 500,
    project_id: int | None = None,
) -> dict[str, Any]:
    """Inspect tasks close to their due date and stage reminder notifications.

    Filters for incomplete tasks assigned to a user whose due date is on or before
    the threshold. Tasks are read in batches of batch_size (one dedup query per batch,
    no N+1), and each batch is committed on its own. Each reminder is inserted in its
    own savepoint, so a row that fails (e.g. its task was deleted meanwhile) is logged
    and skipped instead of rolling back the rest. An assignee gets at most one reminder
    per task and due date within the deduplication window. project_id limits the sweep
    to one project (used by the demo script).
    """
    # Due dates are compared against the UTC calendar day, not the worker's local timezone
    today = datetime.now(UTC).date()
    max_due = today + timedelta(days=threshold_days)
    min_due = today - timedelta(days=overdue_cutoff_days)
    cutoff = datetime.now(UTC) - timedelta(hours=dedup_window_hours)

    filters = [
        TaskModel.due_date.is_not(None),
        TaskModel.assignee_id.is_not(None),
        TaskModel.status != TaskStatus.done,
        TaskModel.due_date >= min_due,
        TaskModel.due_date <= max_due,
    ]
    if project_id is not None:
        filters.append(TaskModel.project_id == project_id)

    tasks_checked = 0
    reminders_created = 0
    reminders_skipped = 0
    reminders_failed = 0
    reminded_task_ids: list[int] = []
    after: tuple[date, int] | None = None

    while True:
        stmt = select(TaskModel).where(*filters)
        if after is not None:
            # Keyset pagination over the (due_date, id) ordering
            stmt = stmt.where(tuple_(TaskModel.due_date, TaskModel.id) > after)
        stmt = stmt.order_by(TaskModel.due_date.asc(), TaskModel.id.asc()).limit(batch_size)
        tasks = (await db.scalars(stmt)).all()
        if not tasks:
            break
        last = tasks[-1]
        if last.due_date is None:  # excluded by the query; narrows the type
            break
        after = (last.due_date, last.id)
        tasks_checked += len(tasks)

        # Batch-fetch the (task, recipient, due date) reminders already sent in the window.
        # Keyed per recipient so a reassigned task still reminds its new assignee, and per
        # due date so moving the due date reminds again for the new date.
        existing = await db.execute(
            select(
                Notification.task_id,
                Notification.recipient_id,
                Notification.payload["due_date"].astext,
            ).where(
                Notification.task_id.in_([t.id for t in tasks]),
                Notification.type == "TASK_DUE_REMINDER",
                Notification.created_at >= cutoff,
            )
        )
        already_reminded = {(t_id, r_id, due) for t_id, r_id, due in existing}

        for task in tasks:
            recipient_id = task.assignee_id
            if recipient_id is None or task.due_date is None:  # excluded by the query
                continue

            if (task.id, recipient_id, task.due_date.isoformat()) in already_reminded:
                reminders_skipped += 1
                logger.debug(
                    "Skipping reminder for task %s (recipient %s): already sent in dedup window",
                    task.id,
                    recipient_id,
                )
                continue

            try:
                async with db.begin_nested():
                    db.add(_reminder_for(task, recipient_id, today))
            except SQLAlchemyError as exc:
                reminders_failed += 1
                logger.warning(
                    "Could not stage reminder for task %s (recipient %s); skipping it: %s",
                    task.id,
                    recipient_id,
                    exc,
                )
                continue
            reminders_created += 1
            reminded_task_ids.append(task.id)

        await db.commit()
        if len(tasks) < batch_size:
            break

    return {
        "status": "success",
        "tasks_checked": tasks_checked,
        "reminders_created": reminders_created,
        "reminders_skipped": reminders_skipped,
        "reminders_failed": reminders_failed,
        "reminded_task_ids": reminded_task_ids,
    }


async def _process_due_task_reminders(
    threshold_days: int | None = None,
    dedup_window_hours: int | None = None,
    db: AsyncSession | None = None,
    redis_client: aioredis.Redis | None = None,
    lock_key: str = REMINDER_LOCK_KEY,
    project_id: int | None = None,
) -> dict[str, Any]:
    """Execute the due task reminder sweep wrapped in a Redis distributed lock.

    The lock expires after settings.due_reminder_lock_ttl_seconds and is renewed while
    the sweep runs, so a slow sweep keeps it and the next Beat tick skips. lock_key and
    project_id let the demo script run an isolated sweep next to the real one.
    """
    target_threshold = (
        threshold_days if threshold_days is not None else settings.due_reminder_window_days
    )
    target_dedup_hours = (
        dedup_window_hours if dedup_window_hours is not None else settings.due_reminder_dedup_hours
    )

    # The caller's client (tests, the demo) stays open; one created here is closed here.
    client = redis_client if redis_client is not None else create_redis_client()
    try:
        async with distributed_lock(
            client,
            lock_key,
            timeout_seconds=settings.due_reminder_lock_ttl_seconds,
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
                    db,
                    threshold_days=target_threshold,
                    dedup_window_hours=target_dedup_hours,
                    batch_size=settings.due_reminder_batch_size,
                    project_id=project_id,
                )

            async with get_worker_db() as worker_db:
                return await _execute_due_task_reminders(
                    worker_db,
                    threshold_days=target_threshold,
                    dedup_window_hours=target_dedup_hours,
                    batch_size=settings.due_reminder_batch_size,
                    project_id=project_id,
                )
    finally:
        if redis_client is None:
            await client.aclose()


@celery_app.task(
    name="app.tasks.reminder_tasks.send_due_task_reminders",
    max_retries=0,
)
def send_due_task_reminders(
    threshold_days: int | None = None,
    dedup_window_hours: int | None = None,
) -> dict[str, Any]:
    """Celery Beat periodic task entrypoint for due-task reminders.

    Prevents overlapping executions via Redis distributed lock and deduplicates
    reminders within the specified window.

    Failures are not retried: Beat runs the sweep again on its next tick, and the
    deduplication window makes a re-run safe. A retry would only race the next tick
    for the lock, and retrying deterministic errors (IntegrityError, bugs) is wasted work.
    """
    logger.info("Executing scheduled due-task reminder sweep.")
    try:
        return run_async(
            _process_due_task_reminders(
                threshold_days=threshold_days,
                dedup_window_hours=dedup_window_hours,
            )
        )
    except Exception:
        logger.exception("Due-task reminder sweep failed; Beat runs it again on the next tick.")
        raise
