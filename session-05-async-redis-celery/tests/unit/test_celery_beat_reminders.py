"""Unit tests for Celery Beat reminder tasks, Redis distributed locks, and beat schedule."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.celery_app import celery_app
from app.tasks.locks import acquire_redis_lock, distributed_lock, release_redis_lock
from app.tasks.reminder_tasks import (
    _process_due_task_reminders,
    send_due_task_reminders,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_and_release_redis_lock_success() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    mock_redis.eval.return_value = 1

    token = await acquire_redis_lock(mock_redis, "test_key", timeout_seconds=60)
    assert token is not None
    mock_redis.set.assert_called_once_with("test_key", token, nx=True, ex=60)

    released = await release_redis_lock(mock_redis, "test_key", token)
    assert released is True
    mock_redis.eval.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_redis_lock_already_held() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Lock already exists

    token = await acquire_redis_lock(mock_redis, "test_key", timeout_seconds=60)
    assert token is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_release_redis_lock_mismatched_token() -> None:
    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 0  # Token didn't match current lock holder

    released = await release_redis_lock(mock_redis, "test_key", "wrong_token")
    assert released is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_distributed_lock_context_manager_acquires_and_releases() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    mock_redis.eval.return_value = 1

    async with distributed_lock("test_key", redis_client=mock_redis) as token:
        assert token is not None

    mock_redis.eval.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_due_task_reminders_skips_when_lock_held() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Lock already held

    result = await _process_due_task_reminders(redis_client=mock_redis)
    assert result["status"] == "skipped"
    assert result["reason"] == "overlapping_run"
    assert result["reminders_created"] == 0


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
    assert task.max_retries == 2


@pytest.mark.unit
@patch("app.tasks.reminder_tasks._process_due_task_reminders", new_callable=AsyncMock)
def test_send_due_task_reminders_task_invokes_process(mock_process: AsyncMock) -> None:
    mock_process.return_value = {"status": "success", "reminders_created": 2}
    result = send_due_task_reminders(threshold_days=2)
    assert result["status"] == "success"
    mock_process.assert_called_once_with(threshold_days=2, dedup_window_hours=24)
