"""Task status changes and assignments made through the API publish task events."""

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.events import publisher as publisher_module
from app.events.schemas import TaskEventType
from app.models.enums import ProjectRole, TaskStatus
from tests.fixtures.events import stream_events
from tests.fixtures.factories import DataFactory


async def test_status_change_publishes_status_changed_event(
    client: AsyncClient, factory: DataFactory, redis_client: Redis
) -> None:
    project = await factory.project()
    assignee = await factory.member(project)
    task = await factory.task(project, assignee=assignee.id)

    resp = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": "in_progress"},
        headers={**assignee.headers, "X-Request-ID": "evt-test-1"},
    )

    assert resp.status_code == 200
    [event] = await stream_events(redis_client)
    assert event.event_type is TaskEventType.status_changed
    assert (event.task_id, event.project_id, event.workspace_id) == (
        task.id,
        project.id,
        project.workspace_id,
    )
    assert event.actor_id == assignee.id
    assert event.request_id == "evt-test-1"
    assert event.data == {"previous_status": "todo", "new_status": "in_progress"}


async def test_rejected_status_change_publishes_nothing(
    client: AsyncClient, factory: DataFactory, redis_client: Redis
) -> None:
    project = await factory.project()
    assignee = await factory.member(project)
    task = await factory.task(project, assignee=assignee.id)

    resp = await client.patch(
        f"/api/v1/tasks/{task.id}/status", json={"status": "done"}, headers=assignee.headers
    )

    assert resp.status_code == 400
    assert await stream_events(redis_client) == []


async def test_same_status_again_publishes_nothing(
    client: AsyncClient, factory: DataFactory, redis_client: Redis
) -> None:
    project = await factory.project()
    assignee = await factory.member(project)
    task = await factory.task(project, assignee=assignee.id, status=TaskStatus.in_progress)

    resp = await client.patch(
        f"/api/v1/tasks/{task.id}/status", json={"status": "in_progress"}, headers=assignee.headers
    )

    assert resp.status_code == 200
    assert await stream_events(redis_client) == []


async def test_assignment_publishes_assigned_event(
    client: AsyncClient, factory: DataFactory, redis_client: Redis
) -> None:
    project = await factory.project()
    manager = await factory.member(project, ProjectRole.manager)
    assignee = await factory.member(project)
    task = await factory.task(project)

    resp = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": assignee.id},
        headers=manager.headers,
    )

    assert resp.status_code == 200
    [event] = await stream_events(redis_client)
    assert event.event_type is TaskEventType.assigned
    assert event.actor_id == manager.id
    assert event.data == {"previous_assignee_id": None, "new_assignee_id": assignee.id}


async def test_assign_with_status_change_publishes_both_events(
    client: AsyncClient, factory: DataFactory, redis_client: Redis
) -> None:
    project = await factory.project()
    manager = await factory.member(project, ProjectRole.manager)
    assignee = await factory.member(project)
    task = await factory.task(project)

    resp = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": assignee.id, "status": "in_progress"},
        headers=manager.headers,
    )

    assert resp.status_code == 200
    events = await stream_events(redis_client)
    assert [e.event_type for e in events] == [TaskEventType.status_changed, TaskEventType.assigned]


async def test_unassignment_publishes_unassigned_event(
    client: AsyncClient, factory: DataFactory, redis_client: Redis
) -> None:
    project = await factory.project()
    manager = await factory.member(project, ProjectRole.manager)
    assignee = await factory.member(project)
    task = await factory.task(project, assignee=assignee.id)

    resp = await client.post(
        f"/api/v1/tasks/{task.id}/assign", json={"assignee_id": None}, headers=manager.headers
    )

    assert resp.status_code == 200
    [event] = await stream_events(redis_client)
    assert event.event_type is TaskEventType.unassigned
    assert event.data == {"previous_assignee_id": assignee.id, "new_assignee_id": None}


async def test_failed_assignment_transaction_publishes_nothing(
    client: AsyncClient, factory: DataFactory, redis_client: Redis
) -> None:
    project = await factory.project()
    manager = await factory.member(project, ProjectRole.manager)
    assignee = await factory.member(project)
    task = await factory.task(project)

    resp = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": assignee.id, "simulate_failure": True},
        headers=manager.headers,
    )

    assert resp.status_code >= 400
    assert await stream_events(redis_client) == []


async def test_redis_outage_does_not_fail_the_request(
    client: AsyncClient,
    factory: DataFactory,
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreachable = Redis(port=1, socket_connect_timeout=0.2)  # nothing listens on port 1
    monkeypatch.setattr(publisher_module, "get_redis_client", lambda: unreachable)
    project = await factory.project()
    assignee = await factory.member(project)
    task = await factory.task(project, assignee=assignee.id)

    resp = await client.patch(
        f"/api/v1/tasks/{task.id}/status", json={"status": "in_progress"}, headers=assignee.headers
    )
    await unreachable.aclose()

    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"
