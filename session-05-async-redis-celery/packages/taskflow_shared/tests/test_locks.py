"""Unit tests for taskflow_shared.locks (Redis replaced by a mock)."""

from unittest.mock import AsyncMock

from taskflow_shared.locks import acquire_redis_lock, distributed_lock, release_redis_lock


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


async def test_acquire_redis_lock_already_held() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Lock already exists

    token = await acquire_redis_lock(mock_redis, "test_key", timeout_seconds=60)
    assert token is None


async def test_release_redis_lock_mismatched_token() -> None:
    mock_redis = AsyncMock()
    mock_redis.eval.return_value = 0  # Token didn't match current lock holder

    released = await release_redis_lock(mock_redis, "test_key", "wrong_token")
    assert released is False


async def test_distributed_lock_context_manager_acquires_and_releases() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    mock_redis.eval.return_value = 1

    async with distributed_lock(mock_redis, "test_key") as token:
        assert token is not None

    mock_redis.eval.assert_called_once()
    mock_redis.aclose.assert_not_called()  # the caller owns the client


async def test_distributed_lock_yields_none_when_held_and_releases_nothing() -> None:
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None

    async with distributed_lock(mock_redis, "test_key") as token:
        assert token is None

    mock_redis.eval.assert_not_called()
