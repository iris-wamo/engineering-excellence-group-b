"""Unit tests for the task summary cache (Redis replaced by a mock)."""

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache.task_summary_cache import (
    SummaryLookup,
    invalidate_summary,
    lookup_summary,
    store_summary,
    summary_key,
    version_key,
)
from app.core.config import settings

METRICS = {
    "counts_by_status": {"todo": 1, "in_progress": 0, "review": 0, "done": 2},
    "overdue_count": 1,
    "assigned_count": 2,
    "total_count": 3,
}


@pytest.fixture()
def redis() -> Iterator[MagicMock]:
    client = MagicMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock()
    client.incr = AsyncMock(return_value=1)
    with patch("app.cache.task_summary_cache.get_redis_client", return_value=client):
        yield client


def test_keys_are_namespaced_by_workspace_and_version() -> None:
    assert summary_key(7, 3) == "taskflow:v1:ws:7:task_summary:v3"
    assert version_key(7) == "taskflow:v1:ws:7:task_summary:version"
    assert summary_key(1, 0) != summary_key(2, 0)


async def test_lookup_miss_reports_version_zero_when_never_invalidated(redis: MagicMock) -> None:
    assert await lookup_summary(1) == SummaryLookup(metrics=None, version=0)
    redis.get.assert_any_await(summary_key(1, 0))


async def test_lookup_hit_reads_the_entry_for_the_current_version(redis: MagicMock) -> None:
    redis.get.side_effect = lambda key: {
        version_key(1): "4",
        summary_key(1, 4): json.dumps(METRICS),
    }.get(key)

    assert await lookup_summary(1) == SummaryLookup(metrics=METRICS, version=4)


async def test_lookup_fails_open_when_redis_is_down(redis: MagicMock) -> None:
    redis.get.side_effect = RedisConnectionError("down")

    assert await lookup_summary(1) == SummaryLookup(metrics=None, version=None)


@pytest.mark.parametrize("stored", ["not json", "null", "[1, 2]", '{"total_count": 1}'])
async def test_lookup_treats_a_corrupt_or_wrongly_shaped_entry_as_a_miss(
    redis: MagicMock, stored: str
) -> None:
    redis.get.side_effect = lambda key: stored if key == summary_key(1, 0) else None

    assert await lookup_summary(1) == SummaryLookup(metrics=None, version=0)


@pytest.mark.parametrize(
    "bad",
    [
        {"overdue_count": "1"},
        {"assigned_count": None},
        {"total_count": 3.5},
        {"total_count": True},
        {"counts_by_status": []},
        {"counts_by_status": {"todo": "1"}},
    ],
)
async def test_lookup_treats_wrongly_typed_metric_values_as_a_miss(
    redis: MagicMock, bad: dict[str, object]
) -> None:
    stored = json.dumps({**METRICS, **bad})
    redis.get.side_effect = lambda key: stored if key == summary_key(1, 0) else None

    assert await lookup_summary(1) == SummaryLookup(metrics=None, version=0)


async def test_store_sets_the_entry_with_the_configured_ttl(redis: MagicMock) -> None:
    await store_summary(1, 2, METRICS)

    redis.set.assert_awaited_once_with(
        summary_key(1, 2), json.dumps(METRICS), ex=settings.task_summary_cache_ttl_seconds
    )


async def test_store_is_skipped_without_a_version(redis: MagicMock) -> None:
    await store_summary(1, None, METRICS)

    redis.set.assert_not_awaited()


async def test_store_swallows_redis_errors(redis: MagicMock) -> None:
    redis.set.side_effect = RedisConnectionError("down")

    await store_summary(1, 0, METRICS)


async def test_invalidate_bumps_the_workspace_version(redis: MagicMock) -> None:
    await invalidate_summary(5)

    redis.incr.assert_awaited_once_with(version_key(5))


async def test_invalidate_swallows_redis_errors(redis: MagicMock) -> None:
    redis.incr.side_effect = RedisConnectionError("down")

    await invalidate_summary(5)
