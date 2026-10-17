"""Unit tests for Celery task notification exceptions, retry logic, and metadata."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.tasks.exceptions import (
    InvalidAssignmentNotificationError,
    NotificationError,
    NotificationPermanentError,
    NotificationTransientError,
    RecipientNotFoundError,
    TaskNotFoundError,
)
from app.tasks.notification_tasks import send_task_assignment_notification


def test_exception_hierarchy() -> None:
    """Verify transient and permanent notification exceptions inherit correctly."""
    assert issubclass(NotificationTransientError, NotificationError)
    assert issubclass(NotificationPermanentError, NotificationError)
    assert issubclass(TaskNotFoundError, NotificationPermanentError)
    assert issubclass(RecipientNotFoundError, NotificationPermanentError)
    assert issubclass(InvalidAssignmentNotificationError, NotificationPermanentError)


def test_task_configuration_attributes() -> None:
    """Verify task registration name, retry limits, and defaults."""
    assert (
        send_task_assignment_notification.name
        == "app.tasks.notification_tasks.send_task_assignment_notification"
    )
    assert send_task_assignment_notification.max_retries == 3
    assert send_task_assignment_notification.default_retry_delay == 2


def _fail_with(exc: Exception) -> Callable[[Any], None]:
    def side_effect(coro: Any) -> None:
        if hasattr(coro, "close"):
            coro.close()
        raise exc

    return side_effect


@patch("app.tasks.notification_tasks.run_async")
def test_permanent_failure_does_not_retry(mock_run_async: MagicMock) -> None:
    """Permanent errors must raise immediately without triggering task.retry()."""
    mock_run_async.side_effect = _fail_with(TaskNotFoundError("Task 999 not found"))

    mock_task_self = MagicMock()
    mock_task_self.request.retries = 0
    mock_task_self.max_retries = 3

    with pytest.raises(TaskNotFoundError):
        send_task_assignment_notification.__wrapped__.__func__(
            mock_task_self,
            task_id=999,
            recipient_id=1,
            assigned_by_id=None,
        )

    # retry() MUST NOT be called for permanent errors
    mock_task_self.retry.assert_not_called()


@patch("app.tasks.notification_tasks.run_async")
def test_transient_failure_retries_with_backoff(mock_run_async: MagicMock) -> None:
    """Transient errors must trigger self.retry() with exponential backoff."""
    mock_run_async.side_effect = _fail_with(NotificationTransientError("Connection timeout"))

    mock_task_self = MagicMock()
    mock_task_self.request.retries = 1
    mock_task_self.max_retries = 3
    # Configure retry() to raise a sentinel so execution stops
    mock_task_self.retry.side_effect = RuntimeError("Retry triggered")

    with pytest.raises(RuntimeError, match="Retry triggered"):
        send_task_assignment_notification.__wrapped__.__func__(
            mock_task_self,
            task_id=10,
            recipient_id=2,
            assigned_by_id=1,
        )

    # 2 ** retries = 2 ** 1 = 2s countdown
    mock_task_self.retry.assert_called_once()
    _, kwargs = mock_task_self.retry.call_args
    assert kwargs["countdown"] == 2


@patch("app.tasks.notification_tasks.run_async")
def test_operational_error_retries_with_backoff(mock_run_async: MagicMock) -> None:
    """Database OperationalError is transient and triggers retry."""
    mock_run_async.side_effect = _fail_with(OperationalError("connection lost", None, Exception()))

    mock_task_self = MagicMock()
    mock_task_self.request.retries = 0
    mock_task_self.max_retries = 3
    mock_task_self.retry.side_effect = RuntimeError("Retry triggered")

    with pytest.raises(RuntimeError, match="Retry triggered"):
        send_task_assignment_notification.__wrapped__.__func__(
            mock_task_self,
            task_id=10,
            recipient_id=2,
        )

    mock_task_self.retry.assert_called_once()
    _, kwargs = mock_task_self.retry.call_args
    assert kwargs["countdown"] == 1  # 2 ** 0 = 1s


@patch("app.tasks.notification_tasks.run_async")
def test_transient_failure_exhausts_retries_and_marks_failed(mock_run_async: MagicMock) -> None:
    """Exhausting max retries must not retry further and must re-raise the exception."""
    calls = 0

    def side_effect(coro: Any) -> None:
        nonlocal calls
        if hasattr(coro, "close"):
            coro.close()
        calls += 1
        if calls == 1:
            raise NotificationTransientError("Persistent network outage")
        return None

    mock_run_async.side_effect = side_effect

    mock_task_self = MagicMock()
    mock_task_self.request.retries = 3
    mock_task_self.max_retries = 3

    with pytest.raises(NotificationTransientError, match="Persistent network outage"):
        send_task_assignment_notification.__wrapped__.__func__(
            mock_task_self,
            task_id=10,
            recipient_id=2,
        )

    # Because retries == max_retries, retry() is NOT called
    mock_task_self.retry.assert_not_called()


@pytest.mark.asyncio
async def test_process_assignment_notification_simulate_permanent_failure() -> None:
    """Verifies simulated permanent failure flag raises NotificationPermanentError."""
    from app.tasks.notification_tasks import _process_assignment_notification

    with pytest.raises(NotificationPermanentError, match="Simulated permanent failure"):
        await _process_assignment_notification(
            task_id=1,
            recipient_id=2,
            simulate_permanent_failure=True,
        )


@pytest.mark.asyncio
async def test_process_assignment_notification_simulate_transient_failure() -> None:
    """Verifies simulated transient failure flag raises NotificationTransientError."""
    from app.tasks.notification_tasks import _process_assignment_notification

    with pytest.raises(NotificationTransientError, match="Simulated transient failure"):
        await _process_assignment_notification(
            task_id=1,
            recipient_id=2,
            simulate_transient_failures=2,
            current_retry=0,
        )
