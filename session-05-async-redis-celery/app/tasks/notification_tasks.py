"""Celery background tasks for task assignment notifications."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import Task
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.concurrency import run_async
from taskflow_shared.errors import PermanentError, TransientError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.models.notification import Notification
from app.models.task import Task as TaskModel
from app.models.user import User
from app.tasks.db import get_worker_db
from app.tasks.exceptions import (
    InvalidAssignmentNotificationError,
    NotificationNotFoundError,
    NotificationPermanentError,
    NotificationTransientError,
    RecipientNotFoundError,
    TaskNotFoundError,
)

logger = logging.getLogger(__name__)


async def _execute_assignment_notification(
    db: AsyncSession,
    notification_id: int,
) -> dict[str, Any]:
    # 1. Find which task the outbox row belongs to (no lock yet)
    task_id = await db.scalar(
        select(Notification.task_id).where(Notification.id == notification_id)
    )
    if task_id is None:
        if await db.get(Notification, notification_id) is None:
            raise NotificationNotFoundError(f"Notification with id {notification_id} not found.")
        raise InvalidAssignmentNotificationError(
            f"Notification {notification_id} is not a task assignment notification."
        )

    # 2. Lock the task, then the row, in the same order as TaskService.assign_task. A
    #    reassignment in flight holds the task lock, so delivery waits for it to commit and
    #    then sees the row it cancelled, instead of notifying the replaced assignee.
    task = await db.scalar(
        select(TaskModel)
        .where(TaskModel.id == task_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )

    # 3. Lock the outbox row this job was dispatched for. The row id is the idempotency key:
    #    a redelivered or concurrently running copy of the job waits here, then sees 'sent'.
    notification = await db.scalar(
        select(Notification)
        .where(Notification.id == notification_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if notification is None:
        raise NotificationNotFoundError(f"Notification with id {notification_id} not found.")
    if notification.type != "TASK_ASSIGNED":
        raise InvalidAssignmentNotificationError(
            f"Notification {notification_id} is not a task assignment notification."
        )

    recipient_id = notification.recipient_id
    result: dict[str, Any] = {
        "notification_id": notification.id,
        "task_id": task_id,
        "recipient_id": recipient_id,
    }

    # 4. Idempotency check: only a 'pending' row is ever delivered
    if notification.status != "pending":
        logger.info(
            "Notification %s is already '%s'. Skipping duplicate delivery (idempotent).",
            notification.id,
            notification.status,
        )
        status = "already_sent" if notification.status == "sent" else "skipped"
        return {**result, "status": status, "idempotent": True}

    # 5. Validate task and recipient existence (permanent errors if missing)
    if not task:
        raise TaskNotFoundError(f"Task with id {task_id} not found.")
    recipient = await db.get(User, recipient_id)
    if not recipient:
        raise RecipientNotFoundError(f"Recipient user with id {recipient_id} not found.")

    # 6. Verify task is still assigned to recipient
    if task.assignee_id != recipient_id:
        raise InvalidAssignmentNotificationError(
            f"Task {task_id} is assigned to user {task.assignee_id}, not {recipient_id}."
        )

    # 7. Deliver: transition the row to 'sent'
    notification.status = "sent"
    payload = dict(notification.payload or {})
    payload.update({"task_title": task.title, "dispatched": True})
    notification.payload = payload
    await db.commit()
    logger.info(
        "Transitioned pending notification %s to 'sent' for task %s to recipient %s.",
        notification.id,
        task_id,
        recipient_id,
    )
    return {**result, "status": "sent", "idempotent": False}


async def _process_assignment_notification(
    notification_id: int,
    simulate_transient_failures: int = 0,
    simulate_permanent_failure: bool = False,
    current_retry: int = 0,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Execute the notification delivery logic inside an isolated async DB session.

    Handles idempotency, validates entities, and supports simulated failure modes.
    """
    if simulate_permanent_failure:
        raise NotificationPermanentError(
            "Simulated permanent failure in assignment notification task."
        )

    if simulate_transient_failures > current_retry:
        msg = (
            f"Simulated transient failure "
            f"(attempt {current_retry + 1} of {simulate_transient_failures})."
        )
        raise NotificationTransientError(msg)

    if db is not None:
        return await _execute_assignment_notification(db, notification_id)

    async with get_worker_db() as worker_db:
        return await _execute_assignment_notification(worker_db, notification_id)


async def _execute_mark_failed(
    db: AsyncSession,
    notification_id: int,
    error_message: str,
) -> None:
    notification = await db.scalar(
        select(Notification).where(Notification.id == notification_id).with_for_update()
    )
    # Never overwrite a row another delivery already completed
    if notification is None or notification.status != "pending":
        return

    notification.status = "failed"
    payload = dict(notification.payload or {})
    payload["error"] = error_message
    notification.payload = payload
    await db.commit()
    logger.info("Marked notification %s as failed.", notification_id)


async def _mark_notification_failed(
    notification_id: int,
    error_message: str,
    db: AsyncSession | None = None,
) -> None:
    """Mark the job's notification row as 'failed' in the database, if still pending."""
    try:
        if db is not None:
            await _execute_mark_failed(db, notification_id, error_message)
        else:
            async with get_worker_db() as worker_db:
                await _execute_mark_failed(worker_db, notification_id, error_message)
    except Exception as exc:
        logger.warning(
            "Could not mark notification %s as failed due to DB error: %s", notification_id, exc
        )


def _is_transient(exc: Exception) -> bool:
    """Return True for failures that can succeed on a later attempt.

    Only connection-level database errors are retried: IntegrityError, ProgrammingError and
    DataError are DBAPIError subclasses too, but they fail the same way every time.
    ConnectionError and TimeoutError are covered by OSError.
    """
    if isinstance(exc, TransientError | OperationalError | InterfaceError | OSError):
        return True
    return isinstance(exc, DBAPIError) and exc.connection_invalidated


@celery_app.task(
    bind=True,
    name="app.tasks.notification_tasks.send_task_assignment_notification",
    max_retries=3,
    default_retry_delay=2,
)
def send_task_assignment_notification(
    self: Task,
    notification_id: int,
    simulate_transient_failures: int = 0,
    simulate_permanent_failure: bool = False,
) -> dict[str, Any]:
    """Celery background task to deliver one task assignment notification row.

    - Retries temporary failures (network blips, DB connection loss) up to max_retries.
    - Does NOT retry permanent failures (non-existent task or user, validation errors) or
      unexpected errors; both mark the row 'failed' with the error recorded.
    - Idempotent: keyed on notification_id, so redelivery never sends the same row twice.
    """
    try:
        return run_async(
            _process_assignment_notification(
                notification_id=notification_id,
                simulate_transient_failures=simulate_transient_failures,
                simulate_permanent_failure=simulate_permanent_failure,
                current_retry=self.request.retries,
            )
        )
    except PermanentError as exc:
        logger.error(
            "Permanent failure for notification %s: %s. Not retrying.",
            notification_id,
            exc,
        )
        run_async(_mark_notification_failed(notification_id, str(exc)))
        raise
    except Exception as exc:
        if not _is_transient(exc):
            logger.exception(
                "Unexpected error for notification %s: %s. Not retrying; marking failed.",
                notification_id,
                exc,
            )
            run_async(_mark_notification_failed(notification_id, f"{type(exc).__name__}: {exc}"))
            raise
        if self.request.retries < self.max_retries:
            countdown = 2**self.request.retries
            logger.warning(
                "Temporary failure sending notification %s (attempt %s/%s): %s. Retrying in %ss...",
                notification_id,
                self.request.retries + 1,
                self.max_retries,
                exc,
                countdown,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        logger.error(
            "Exhausted maximum retries (%s) for notification %s: %s. Marking failed.",
            self.max_retries,
            notification_id,
            exc,
        )
        run_async(_mark_notification_failed(notification_id, str(exc)))
        raise


def enqueue_assignment_notification(notification_id: int) -> None:
    """Publish the delivery job for one outbox row.

    Blocking (kombu publishes synchronously): call it via asyncio.to_thread from async code.
    retry=False plus the broker socket timeouts in celery_app make a down broker fail fast;
    the row stays 'pending' and the stale-pending sweep re-publishes it.
    """
    send_task_assignment_notification.apply_async(
        kwargs={"notification_id": notification_id}, retry=False
    )


async def _requeue_stale_pending_notifications(
    db: AsyncSession,
    older_than_minutes: int,
    limit: int,
    max_attempts: int,
    publish: Callable[[int], None],
) -> dict[str, list[int]]:
    """Re-publish pending assignment rows untouched for older_than_minutes.

    Rows stay locked while they are published, and payload.requeue_count is bumped only
    after the broker accepts a row's job, so a failed publish never counts as an attempt.
    The bump also refreshes updated_at, so a row is re-published at most once per window,
    and the oldest-touched rows go first. The first failed publish stops the batch (the
    broker is most likely down); unpublished rows are left untouched for the next sweep.
    Rows already re-queued max_attempts times are marked 'failed' instead of re-published.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    notifications = (
        await db.scalars(
            select(Notification)
            .where(
                Notification.type == "TASK_ASSIGNED",
                Notification.status == "pending",
                Notification.updated_at < cutoff,
            )
            .order_by(Notification.updated_at.asc(), Notification.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()

    requeued: list[int] = []
    given_up: list[int] = []
    not_published: list[int] = []
    publishing = True
    for notification in notifications:
        payload = dict(notification.payload or {})
        attempts = int(payload.get("requeue_count", 0))
        if attempts >= max_attempts:
            notification.status = "failed"
            payload["error"] = f"Not delivered after {attempts} re-queues."
            notification.payload = payload
            given_up.append(notification.id)
            continue

        if publishing:
            try:
                publish(notification.id)
            except Exception as exc:
                logger.warning(
                    "Could not re-publish notification %s; leaving the rest of the batch "
                    "for the next sweep: %s",
                    notification.id,
                    exc,
                )
                publishing = False
        if not publishing:
            not_published.append(notification.id)
            continue

        payload["requeue_count"] = attempts + 1
        notification.payload = payload
        requeued.append(notification.id)

    if notifications:
        await db.commit()  # saves the bumps and releases the row locks
    return {"requeued": requeued, "given_up": given_up, "not_published": not_published}


async def _process_stale_pending_notifications(
    older_than_minutes: int,
    limit: int,
    max_attempts: int,
    publish: Callable[[int], None],
    db: AsyncSession | None = None,
) -> dict[str, list[int]]:
    if db is not None:
        return await _requeue_stale_pending_notifications(
            db, older_than_minutes, limit, max_attempts, publish
        )

    async with get_worker_db() as worker_db:
        return await _requeue_stale_pending_notifications(
            worker_db, older_than_minutes, limit, max_attempts, publish
        )


@celery_app.task(name="app.tasks.notification_tasks.requeue_stale_assignment_notifications")
def requeue_stale_assignment_notifications() -> dict[str, Any]:
    """Celery Beat outbox sweep: re-publish assignment notifications stuck in 'pending'.

    Covers a failed post-commit publish (broker down) and a lost job (worker crash outside
    acks_late redelivery). Re-publishing a row that is still in flight is safe: the delivery
    job locks the row and skips anything no longer 'pending'.
    """
    claimed = run_async(
        _process_stale_pending_notifications(
            older_than_minutes=settings.notification_requeue_after_minutes,
            limit=settings.notification_requeue_batch_size,
            max_attempts=settings.notification_requeue_max_attempts,
            publish=enqueue_assignment_notification,
        )
    )

    if claimed["requeued"]:
        logger.warning(
            "Re-queued %s stale pending assignment notifications: %s",
            len(claimed["requeued"]),
            claimed["requeued"],
        )
    if claimed["given_up"]:
        logger.error(
            "Marked %s assignment notifications failed after %s re-queues: %s",
            len(claimed["given_up"]),
            settings.notification_requeue_max_attempts,
            claimed["given_up"],
        )
    if claimed["not_published"]:
        logger.error(
            "Broker rejected the re-queue; %s pending notifications left for the next sweep: %s",
            len(claimed["not_published"]),
            claimed["not_published"],
        )
    return {
        "requeued": len(claimed["requeued"]),
        "notification_ids": claimed["requeued"],
        "given_up": claimed["given_up"],
        "not_published": claimed["not_published"],
    }
