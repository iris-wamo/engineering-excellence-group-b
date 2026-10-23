"""Integration tests for caching GET /api/v1/tasks/summary in Redis."""

import asyncio
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.cache.task_summary_cache import summary_key, version_key
from app.core.config import settings
from app.repositories.task_repository import TaskRepository
from tests.fixtures.auth import auth_headers_for
from tests.fixtures.factories import DataFactory

SUMMARY_URL = "/api/v1/tasks/summary?external_delay=0.0"


async def test_first_request_misses_and_the_next_one_hits(
    client: AsyncClient, redis_client: Redis, viewer_headers: dict[str, str]
) -> None:
    with patch.object(
        TaskRepository, "get_summary_metrics", wraps=TaskRepository.get_summary_metrics
    ) as query:
        first = await client.get(SUMMARY_URL, headers=viewer_headers)
        assert await redis_client.exists(summary_key(1, 0)) == 1
        second = await client.get(SUMMARY_URL, headers=viewer_headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["counts_by_status"] == second.json()["counts_by_status"]
    assert query.call_count == 1


async def test_blocking_endpoint_shares_the_cache(
    client: AsyncClient, redis_client: Redis, viewer_headers: dict[str, str]
) -> None:
    await client.get(SUMMARY_URL, headers=viewer_headers)

    with patch.object(TaskRepository, "get_summary_metrics") as query:
        response = await client.get(
            "/api/v1/tasks/summary/blocking?external_delay=0.0", headers=viewer_headers
        )

    assert response.status_code == 200
    query.assert_not_called()


async def test_external_call_is_not_cached(
    client: AsyncClient, redis_client: Redis, viewer_headers: dict[str, str]
) -> None:
    await client.get(SUMMARY_URL, headers=viewer_headers)

    slow = await client.get(
        "/api/v1/tasks/summary?external_delay=2.0&external_timeout=0.1", headers=viewer_headers
    )

    assert slow.status_code == 504


async def test_cached_value_expires_after_its_ttl(
    client: AsyncClient,
    redis_client: Redis,
    viewer_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "task_summary_cache_ttl_seconds", 1)

    await client.get(SUMMARY_URL, headers=viewer_headers)
    assert 0 < await redis_client.pttl(summary_key(1, 0)) <= 1000
    await asyncio.sleep(1.2)

    assert await redis_client.exists(summary_key(1, 0)) == 0
    with patch.object(
        TaskRepository, "get_summary_metrics", wraps=TaskRepository.get_summary_metrics
    ) as query:
        await client.get(SUMMARY_URL, headers=viewer_headers)
    assert query.call_count == 1


async def test_workspaces_do_not_share_cache_entries(
    client: AsyncClient,
    redis_client: Redis,
    factory: DataFactory,
    viewer_headers: dict[str, str],
) -> None:
    other = await factory.workspace(name="Cache Beta", slug="cache-beta")
    other_user = await factory.user(workspace_ids=(other.id,))

    await client.get(SUMMARY_URL, headers=viewer_headers)
    response = await client.get(
        SUMMARY_URL, headers=auth_headers_for(other_user.id, workspace_id=other.id)
    )

    assert response.json()["workspace_id"] == other.id
    assert await redis_client.exists(summary_key(1, 0), summary_key(other.id, 0)) == 2


async def test_summary_still_works_when_the_version_key_is_unreadable(
    client: AsyncClient, redis_client: Redis, viewer_headers: dict[str, str]
) -> None:
    await redis_client.set(version_key(1), "not-a-number")

    response = await client.get(SUMMARY_URL, headers=viewer_headers)

    assert response.status_code == 200
