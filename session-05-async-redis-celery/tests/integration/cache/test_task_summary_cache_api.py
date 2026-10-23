"""Integration tests for caching GET /api/v1/tasks/summary in Redis."""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.cache.task_summary_cache import (
    invalidate_summary,
    lookup_summary,
    store_summary,
    summary_key,
    version_key,
)
from app.core.config import settings
from app.models.enums import ProjectRole
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


async def _summary(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get(SUMMARY_URL, headers=headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_creating_a_task_clears_the_cached_summary(
    client: AsyncClient, redis_client: Redis, factory: DataFactory
) -> None:
    project = await factory.project()
    owner = await factory.member(project, ProjectRole.owner)
    assert (await _summary(client, owner.headers))["total_count"] == 0

    created = await client.post(
        "/api/v1/tasks", json={"title": "New", "project_id": project.id}, headers=owner.headers
    )

    assert created.status_code == 201
    fresh = await _summary(client, owner.headers)
    assert fresh["total_count"] == 1
    assert fresh["counts_by_status"]["todo"] == 1


async def test_changing_a_status_clears_the_cached_summary(
    client: AsyncClient, redis_client: Redis, factory: DataFactory
) -> None:
    project = await factory.project()
    developer = await factory.member(project)
    task = await factory.task(project, assignee=developer.id)
    assert (await _summary(client, developer.headers))["counts_by_status"]["todo"] == 1

    changed = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": "in_progress"},
        headers=developer.headers,
    )

    assert changed.status_code == 200
    counts = (await _summary(client, developer.headers))["counts_by_status"]
    assert counts["todo"] == 0
    assert counts["in_progress"] == 1


async def test_assigning_a_task_clears_the_cached_summary(
    client: AsyncClient, redis_client: Redis, factory: DataFactory
) -> None:
    project = await factory.project()
    owner = await factory.member(project, ProjectRole.owner)
    assignee = await factory.member(project)
    task = await factory.task(project)
    assert (await _summary(client, owner.headers))["assigned_count"] == 0

    assigned = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": assignee.id, "assigned_by_id": owner.id},
        headers=owner.headers,
    )

    assert assigned.status_code == 200
    assert (await _summary(client, owner.headers))["assigned_count"] == 1


async def test_a_rolled_back_write_does_not_clear_the_cache(
    client: AsyncClient, redis_client: Redis, factory: DataFactory
) -> None:
    project = await factory.project()
    owner = await factory.member(project, ProjectRole.owner)
    assignee = await factory.member(project)
    task = await factory.task(project)
    # The failed request rolls the session back, which expires loaded objects.
    workspace_id = project.workspace_id
    await _summary(client, owner.headers)

    failed = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": assignee.id, "assigned_by_id": owner.id, "simulate_failure": True},
        headers=owner.headers,
    )

    assert failed.status_code == 500
    assert await redis_client.get(version_key(workspace_id)) is None
    assert await redis_client.exists(summary_key(workspace_id, 0)) == 1


async def test_only_the_changed_workspace_is_cleared(
    client: AsyncClient, redis_client: Redis, factory: DataFactory
) -> None:
    project = await factory.project()
    owner = await factory.member(project, ProjectRole.owner)
    other = await factory.workspace(name="Cache Gamma", slug="cache-gamma")
    other_project = await factory.project(workspace=other.id)
    other_owner = await factory.member(other_project, ProjectRole.owner)
    await _summary(client, owner.headers)
    await _summary(client, other_owner.headers)

    await client.post(
        "/api/v1/tasks", json={"title": "New", "project_id": project.id}, headers=owner.headers
    )

    assert await redis_client.get(version_key(project.workspace_id)) == "1"
    assert await redis_client.get(version_key(other.id)) is None
    assert await redis_client.exists(summary_key(other.id, 0)) == 1


async def test_a_summary_computed_before_a_write_is_never_served_after_it(
    redis_client: Redis,
) -> None:
    """A slow reader that stores its result after an invalidation must not poison the cache."""
    stale_lookup = await lookup_summary(1)

    await invalidate_summary(1)
    await store_summary(1, stale_lookup.version, {"total_count": 99})

    assert (await lookup_summary(1)).metrics is None


async def test_importing_a_task_clears_the_cached_summary(
    client: AsyncClient,
    redis_client: Redis,
    factory: DataFactory,
    viewer_headers: dict[str, str],
) -> None:
    project = await factory.project()
    assert (await _summary(client, viewer_headers))["total_count"] == 0

    imported = await client.post(
        "/api/v1/tasks/import",
        json={"raw_payload": {"summary": "Imported", "project_id": project.id}},
    )

    assert imported.status_code == 201
    assert (await _summary(client, viewer_headers))["total_count"] == 1
