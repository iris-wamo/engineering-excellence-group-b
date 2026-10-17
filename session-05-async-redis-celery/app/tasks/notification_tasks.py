"""Celery background tasks for task assignment notifications."""

import logging
from typing import Any

from celery import Task
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.models.notification import Notification
from app.models.task import Task as TaskModel
from app.models.user import User
from app.tasks.db import get_worker_db, run_async
from app.tasks.exceptions import (
    InvalidAssignmentNotificationError,
    NotificationPermanentError,
    NotificationTransientError,
    RecipientNotFoundError,
    TaskNotFoundError,
)

logger = logging.getLogger(__name__)


async def _execute_assignment_notification(
    db: AsyncSession,
    task_id: int,
    recipient_id: int,
    assigned_by_id: int | None = None,
) -> dict[str, Any]:
    # 1. Validate task existence (permanent error if missing)
    task = await db.get(TaskModel, task_id)
    if not task:
        raise TaskNotFoundError(f"Task with id {task_id} not found.")

    # 2. Validate recipient existence (permanent error if missing)
    recipient = await db.get(User, recipient_id)
    if not recipient:
        raise RecipientNotFoundError(f"Recipient user with id {recipient_id} not found.")

    # 3. Verify task is actually assigned to recipient
    if task.assignee_id != recipient_id:
        raise InvalidAssignmentNotificationError(
            f"Task {task_id} is assigned to user {task.assignee_id}, not {recipient_id}."
        )

    # 4. Check for existing notification (Idempotency check)
    existing_notifications = (
        await db.scalars(
            select(Notification)
            .where(
                Notification.task_id == task_id,
                Notification.recipient_id == recipient_id,
                Notification.type == "TASK_ASSIGNED",
            )
            .order_by(Notification.id.desc())
        )
    ).all()

    # If a notification has already been delivered, return without creating duplicate
    for notif in existing_notifications:
        if notif.status == "sent":
            logger.info(
                "Notification %s already marked 'sent' for task %s to recipient %s. "
                "Skipping duplicate delivery (idempotent).",
                notif.id,
                task_id,
                recipient_id,
            )
            return {
                "status": "already_sent",
                "notification_id": notif.id,
                "task_id": task_id,
                "recipient_id": recipient_id,
                "idempotent": True,
            }

    # If an existing pending notification exists, transition it to 'sent'
    pending_notification = next((n for n in existing_notifications if n.status == "pending"), None)

    if pending_notification:
        pending_notification.status = "sent"
        payload = dict(pending_notification.payload or {})
        payload.update(
            {
                "task_title": task.title,
                "assigned_by_id": assigned_by_id,
                "dispatched": True,
            }
        )
        pending_notification.payload = payload
        await db.commit()
        await db.refresh(pending_notification)
        logger.info(
            "Transitioned pending notification %s to 'sent' for task %s to recipient %s.",
            pending_notification.id,
            task_id,
            recipient_id,
        )
        return {
            "status": "sent",
            "notification_id": pending_notification.id,
            "task_id": task_id,
            "recipient_id": recipient_id,
            "idempotent": False,
        }

    # If no notification record exists, create one with 'sent' status
    new_notification = Notification(
        recipient_id=recipient_id,
        task_id=task_id,
        type="TASK_ASSIGNED",
        status="sent",
        payload={
            "task_id": task_id,
            "task_title": task.title,
            "assigned_by_id": assigned_by_id,
            "dispatched": True,
        },
    )
    db.add(new_notification)
    await db.commit()
    await db.refresh(new_notification)
    logger.info(
        "Created sent notification %s for task %s to recipient %s.",
        new_notification.id,
        task_id,
        recipient_id,
    )
    return {
        "status": "sent",
        "notification_id": new_notification.id,
        "task_id": task_id,
        "recipient_id": recipient_id,
        "idempotent": False,
    }


async def _process_assignment_notification(
    task_id: int,
    recipient_id: int,
    assigned_by_id: int | None = None,
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
        return await _execute_assignment_notification(
            db,
            task_id=task_id,
            recipient_id=recipient_id,
            assigned_by_id=assigned_by_id,
        )

    async with get_worker_db() as worker_db:
        return await _execute_assignment_notification(
            worker_db,
            task_id=task_id,
            recipient_id=recipient_id,
            assigned_by_id=assigned_by_id,
        )


async def _execute_mark_failed(
    db: AsyncSession,
    task_id: int,
    recipient_id: int,
    error_message: str,
) -> None:
    notifications = (
        await db.scalars(
            select(Notification)
            .where(
                Notification.task_id == task_id,
                Notification.recipient_id == recipient_id,
                Notification.type == "TASK_ASSIGNED",
                Notification.status == "pending",
            )
            .order_by(Notification.id.desc())
        )
    ).all()

    for notif in notifications:
        notif.status = "failed"
        payload = dict(notif.payload or {})
        payload["error"] = error_message
        notif.payload = payload

    if notifications:
        await db.commit()
        logger.info(
            "Marked %s pending notifications as failed for task %s.",
            len(notifications),
            task_id,
        )


async def _mark_notification_failed(
    task_id: int,
    recipient_id: int,
    error_message: str,
    db: AsyncSession | None = None,
) -> None:
    """Mark any pending notification as 'failed' in the database."""
    try:
        if db is not None:
            await _execute_mark_failed(db, task_id, recipient_id, error_message)
        else:
            async with get_worker_db() as worker_db:
                await _execute_mark_failed(worker_db, task_id, recipient_id, error_message)
    except Exception as exc:
        logger.warning(
            "Could not mark notification as failed for task %s due to DB error: %s", task_id, exc
        )


@celery_app.task(
    bind=True,
    name="tasks.send_task_assignment_notification",
    max_retries=3,
    default_retry_delay=2,
)
def send_task_assignment_notification(
    self: Task,
    task_id: int,
    recipient_id: int,
    assigned_by_id: int | None = None,
    simulate_transient_failures: int = 0,
    simulate_permanent_failure: bool = False,
) -> dict[str, Any]:
    """Celery background task to deliver task assignment notifications.

    - Retries temporary failures (network blips, DB timeouts) up to max_retries.
    - Does NOT retry permanent failures (non-existent task or user, validation errors).
    - Idempotent: running multiple times for the same assignment never duplicates notifications.
    """
    try:
        return run_async(
            _process_assignment_notification(
                task_id=task_id,
                recipient_id=recipient_id,
                assigned_by_id=assigned_by_id,
                simulate_transient_failures=simulate_transient_failures,
                simulate_permanent_failure=simulate_permanent_failure,
                current_retry=self.request.retries,
            )
        )
    except (
        NotificationTransientError,
        OperationalError,
        DBAPIError,
        ConnectionError,
        TimeoutError,
        OSError,
    ) as exc:
        if self.request.retries < self.max_retries:
            countdown = 2**self.request.retries
            logger.warning(
                "Temporary failure sending notification for task %s (attempt %s/%s): %s. "
                "Retrying in %ss...",
                task_id,
                self.request.retries + 1,
                self.max_retries,
                exc,
                countdown,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        else:
            logger.error(
                "Exhausted maximum retries (%s) for task %s notification: %s. Marking failed.",
                self.max_retries,
                task_id,
                exc,
            )
            run_async(_mark_notification_failed(task_id, recipient_id, str(exc)))
            raise
    except NotificationPermanentError as exc:
        logger.error(
            "Permanent failure for task %s notification to user %s: %s. Not retrying.",
            task_id,
            recipient_id,
            exc,
        )
        run_async(_mark_notification_failed(task_id, recipient_id, str(exc)))
        raise
