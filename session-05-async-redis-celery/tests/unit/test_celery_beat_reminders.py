"""Unit tests for Celery Beat reminder tasks and the beat schedule.

The lock itself is tested in packages/taskflow_shared/tests/test_locks.py.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.celery_app import celery_app
from app.tasks.reminder_tasks import (
    _process_due_task_reminders,
    send_due_task_reminders,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_due_task_reminders_skips_when_lock_held() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Lock already held

    result = await _process_due_task_reminders(redis_client=mock_redis)
    assert result["status"] == "skipped"
    assert result["reason"] == "overlapping_run"
    assert result["reminders_created"] == 0
    mock_redis.aclose.assert_not_called()  # the caller's client stays open


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_due_task_reminders_closes_the_client_it_creates() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None

    with patch("app.tasks.reminder_tasks.create_redis_client", return_value=mock_redis):
        result = await _process_due_task_reminders()

    assert result["status"] == "skipped"
    mock_redis.aclose.assert_awaited_once()


@pytest.mark.unit
def test_beat_schedule_configuration() -> None:
    schedule = celery_app.conf.beat_schedule
    assert "send-due-task-reminders-periodic" in schedule
    entry = schedule["send-due-task-reminders-periodic"]
    assert entry["task"] == "app.tasks.reminder_tasks.send_due_task_reminders"
    assert entry["schedule"] > 0


@pytest.mark.unit
def test_celery_task_registration() -> None:
    assert "app.tasks.reminder_tasks.send_due_task_reminders" in celery_app.tasks
    task = celery_app.tasks["app.tasks.reminder_tasks.send_due_task_reminders"]
    # Beat re-runs the sweep on its next tick, so failures are not retried
    assert task.max_retries == 0


@pytest.mark.unit
@patch("app.tasks.reminder_tasks._process_due_task_reminders", new_callable=AsyncMock)
def test_send_due_task_reminders_task_invokes_process(mock_process: AsyncMock) -> None:
    mock_process.return_value = {"status": "success", "reminders_created": 2}
    result = send_due_task_reminders(threshold_days=2)
    assert result["status"] == "success"
    mock_process.assert_called_once_with(threshold_days=2, dedup_window_hours=None)


@pytest.mark.unit
@patch("app.tasks.reminder_tasks._process_due_task_reminders", new_callable=AsyncMock)
def test_send_due_task_reminders_failure_is_raised_not_retried(mock_process: AsyncMock) -> None:
    mock_process.side_effect = ValueError("bug in reminder sweep")

    with patch.object(send_due_task_reminders, "retry") as mock_retry:
        with pytest.raises(ValueError, match="bug in reminder sweep"):
            send_due_task_reminders()

    mock_retry.assert_not_called()
