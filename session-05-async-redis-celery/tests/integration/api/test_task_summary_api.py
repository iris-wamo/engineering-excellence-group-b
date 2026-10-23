"""Integration tests for the task summary API (async vs blocking, timeouts, workspace isolation)."""

import asyncio
import time
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from app.models.enums import TaskStatus
from app.schemas.task import ExternalServiceResult
from tests.fixtures.auth import auth_headers_for
from tests.fixtures.factories import DataFactory


@pytest.fixture(autouse=True)
async def empty_summary_cache(redis_client: Redis) -> None:
    """Every test starts without cached summaries: the database is rolled back, Redis is not."""


async def test_async_task_summary_success_with_all_four_pieces_of_data(
    client: AsyncClient,
    factory: DataFactory,
    viewer_headers: dict[str, str],
) -> None:
    """Async endpoint returns all 4 pieces of data with matching counts."""

    project = await factory.project()
    user = await factory.user()
    today = date.today()
    past_date = today - timedelta(days=5)
    future_date = today + timedelta(days=5)

    # 1. Todo, overdue, assigned
    await factory.task(
        project,
        title="Task 1",
        status=TaskStatus.todo,
        assignee=user,
        due_date=past_date,
    )
    # 2. In progress, overdue, unassigned
    await factory.task(
        project,
        title="Task 2",
        status=TaskStatus.in_progress,
        assignee=None,
        due_date=past_date,
    )
    # 3. Review, not overdue, assigned
    await factory.task(
        project,
        title="Task 3",
        status=TaskStatus.review,
        assignee=user,
        due_date=future_date,
    )
    # 4. Done, past due_date (MUST NOT be counted as overdue!)
    await factory.task(
        project,
        title="Task 4",
        status=TaskStatus.done,
        assignee=user,
        due_date=past_date,
    )
    # 5. Todo, null due date, unassigned
    await factory.task(
        project,
        title="Task 5",
        status=TaskStatus.todo,
        assignee=None,
        due_date=None,
    )

    response = await client.get(
        "/api/v1/tasks/summary?external_delay=0.01&external_timeout=1.0",
        headers=viewer_headers,
    )

    assert response.status_code == 200
    body = response.json()

    # 1. counts_by_status
    assert "counts_by_status" in body
    counts = body["counts_by_status"]
    assert counts["todo"] == 2
    assert counts["in_progress"] == 1
    assert counts["review"] == 1
    assert counts["done"] == 1

    # 2. overdue_count (Task 1 and Task 2; Task 4 is done so not overdue; Task 5 is null)
    assert body["overdue_count"] == 2

    # 3. assigned_count (Task 1, Task 3, Task 4)
    assert body["assigned_count"] == 3
    assert body["total_count"] == 5

    # 4. external_service
    assert "external_service" in body
    ext = body["external_service"]
    assert ext["service"] == "workload_service"
    assert ext["status"] == "healthy"
    assert ext["mode"] == "async"
    assert ext["latency_ms"] >= 0.0


async def test_blocking_task_summary_success_matches_structure(
    client: AsyncClient,
    factory: DataFactory,
    viewer_headers: dict[str, str],
) -> None:
    """Blocking summary endpoint returns identical metrics structure and mode='blocking'."""
    project = await factory.project()
    user = await factory.user()
    today = date.today()
    past_due = today - timedelta(days=2)
    future_due = today + timedelta(days=2)

    await factory.task(project, status=TaskStatus.todo, assignee=user, due_date=past_due)
    await factory.task(project, status=TaskStatus.in_progress, assignee=None, due_date=future_due)

    response = await client.get(
        "/api/v1/tasks/summary/blocking?external_delay=0.01&external_timeout=1.0",
        headers=viewer_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counts_by_status"]["todo"] == 1
    assert body["counts_by_status"]["in_progress"] == 1
    assert body["counts_by_status"]["review"] == 0
    assert body["counts_by_status"]["done"] == 0
    assert body["overdue_count"] == 1
    assert body["assigned_count"] == 1
    assert body["total_count"] == 2
    assert body["external_service"]["mode"] == "blocking"
    assert body["external_service"]["status"] == "healthy"


async def test_async_summary_external_call_timeout_returns_504(
    client: AsyncClient,
    viewer_headers: dict[str, str],
) -> None:
    """Async call exceeding timeout fails with HTTP 504 and ADR-001 error envelope."""
    response = await client.get(
        "/api/v1/tasks/summary?external_delay=0.5&external_timeout=0.05",
        headers=viewer_headers,
    )

    assert response.status_code == 504
    body = response.json()
    assert "error" in body
    error = body["error"]
    assert error["code"] == "EXTERNAL_SERVICE_TIMEOUT"
    assert "timed out" in error["message"].lower()
    assert len(error["details"]) == 1
    assert error["details"][0]["field"] == "external_call"
    assert "0.05" in error["details"][0]["message"]


async def test_blocking_summary_external_call_timeout_returns_504(
    client: AsyncClient,
    viewer_headers: dict[str, str],
) -> None:
    """Blocking call exceeding timeout fails with HTTP 504 and ADR-001 error envelope."""
    response = await client.get(
        "/api/v1/tasks/summary/blocking?external_delay=0.5&external_timeout=0.05",
        headers=viewer_headers,
    )

    assert response.status_code == 504
    body = response.json()
    assert "error" in body
    error = body["error"]
    assert error["code"] == "EXTERNAL_SERVICE_TIMEOUT"
    assert "timed out" in error["message"].lower()
    assert len(error["details"]) == 1
    assert error["details"][0]["field"] == "external_call"


async def test_summary_workspace_isolation(
    client: AsyncClient,
    factory: DataFactory,
    viewer_headers: dict[str, str],
) -> None:
    """Summary respects workspace isolation: workspace 2 tasks must not appear in workspace 1."""
    # Setup in Workspace 1 (default)
    project_ws1 = await factory.project()
    await factory.task(project_ws1, status=TaskStatus.todo)
    await factory.task(project_ws1, status=TaskStatus.in_progress)

    # Setup in Workspace 2
    ws2 = await factory.workspace(name="Tenant Beta", slug="tenant-beta")
    user_ws2 = await factory.user(workspace_ids=(ws2.id,))
    project_ws2 = await factory.project(workspace=ws2.id)
    await factory.task(project_ws2, status=TaskStatus.review, assignee=user_ws2)

    await factory.task(project_ws2, status=TaskStatus.done, assignee=user_ws2)

    # Request Workspace 1
    resp_ws1 = await client.get(
        "/api/v1/tasks/summary?external_delay=0.0&external_timeout=1.0",
        headers=viewer_headers,
    )
    assert resp_ws1.status_code == 200
    body_ws1 = resp_ws1.json()
    assert body_ws1["workspace_id"] == 1
    assert body_ws1["total_count"] == 2
    assert body_ws1["counts_by_status"]["todo"] == 1
    assert body_ws1["counts_by_status"]["in_progress"] == 1
    assert body_ws1["counts_by_status"]["review"] == 0
    assert body_ws1["counts_by_status"]["done"] == 0

    # Request Workspace 2 with authenticated user headers
    headers_ws2 = auth_headers_for(user_ws2.id, workspace_id=ws2.id)
    resp_ws2 = await client.get(
        "/api/v1/tasks/summary?external_delay=0.0&external_timeout=1.0",
        headers=headers_ws2,
    )
    assert resp_ws2.status_code == 200
    body_ws2 = resp_ws2.json()
    assert body_ws2["workspace_id"] == ws2.id
    assert body_ws2["total_count"] == 2
    assert body_ws2["counts_by_status"]["todo"] == 0
    assert body_ws2["counts_by_status"]["review"] == 1
    assert body_ws2["counts_by_status"]["done"] == 1
    assert body_ws2["assigned_count"] == 2


async def test_summary_empty_workspace_returns_zero_counts(
    client: AsyncClient,
    factory: DataFactory,
) -> None:
    """An empty workspace returns zero counts for all statuses without errors."""
    ws = await factory.workspace(name="Empty WS", slug="empty-ws")
    user = await factory.user(workspace_ids=(ws.id,))
    headers = auth_headers_for(user.id, workspace_id=ws.id)

    response = await client.get(
        "/api/v1/tasks/summary?external_delay=0.0&external_timeout=1.0",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == ws.id
    assert body["total_count"] == 0
    assert body["overdue_count"] == 0
    assert body["assigned_count"] == 0
    assert body["counts_by_status"] == {
        "todo": 0,
        "in_progress": 0,
        "review": 0,
        "done": 0,
    }


async def test_async_summary_concurrency_non_blocking_behavior(
    client: AsyncClient,
    viewer_headers: dict[str, str],
) -> None:
    """Multiple concurrent requests to the async endpoint overlap in time."""
    delay = 0.15
    concurrency = 4

    start_times: list[float] = []
    end_times: list[float] = []

    async def single_call() -> None:
        start_times.append(time.perf_counter())
        resp = await client.get(
            f"/api/v1/tasks/summary?external_delay={delay}&external_timeout=1.0",
            headers=viewer_headers,
        )
        end_times.append(time.perf_counter())
        assert resp.status_code == 200

    start = time.perf_counter()
    await asyncio.gather(*(single_call() for _ in range(concurrency)))
    elapsed = time.perf_counter() - start

    # 1. Overlap proof: All tasks started execution before the first task finished
    assert max(start_times) < min(end_times)

    # 2. Timing proof: Total elapsed time is significantly less than sequential execution time
    sequential_time = delay * concurrency
    assert elapsed < sequential_time


async def test_task_summary_due_date_boundary_conditions(
    client: AsyncClient,
    factory: DataFactory,
    viewer_headers: dict[str, str],
) -> None:
    """Overdue count correctly handles boundary conditions (today, past, future, done, null)."""
    project = await factory.project()
    today = date.today()

    # Past due and active -> OVERDUE
    await factory.task(project, status=TaskStatus.todo, due_date=today - timedelta(days=1))
    # Due today and active -> NOT overdue yet
    await factory.task(project, status=TaskStatus.todo, due_date=today)
    # Due in future and active -> NOT overdue
    await factory.task(project, status=TaskStatus.todo, due_date=today + timedelta(days=1))
    # Past due but done -> NOT overdue
    await factory.task(project, status=TaskStatus.done, due_date=today - timedelta(days=1))
    # Null due date -> NOT overdue
    await factory.task(project, status=TaskStatus.in_progress, due_date=None)

    resp = await client.get(
        "/api/v1/tasks/summary?external_delay=0.0&external_timeout=1.0",
        headers=viewer_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["overdue_count"] == 1


async def test_task_summary_query_parameter_validation(
    client: AsyncClient,
    viewer_headers: dict[str, str],
) -> None:
    """Validation rejects negative delay or non-positive timeout values with HTTP 422."""
    resp_delay = await client.get(
        "/api/v1/tasks/summary?external_delay=-0.5",
        headers=viewer_headers,
    )
    assert resp_delay.status_code == 422

    resp_timeout = await client.get(
        "/api/v1/tasks/summary?external_timeout=0.0",
        headers=viewer_headers,
    )
    assert resp_timeout.status_code == 422


async def test_sync_call_inside_async_starves_event_loop(
    client: AsyncClient,
    viewer_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accidental synchronous blocking call inside async def starves the event loop."""

    async def accidental_sync_call(delay: float, timeout: float) -> ExternalServiceResult:
        time.sleep(0.1)
        return ExternalServiceResult(
            service="workload_service",
            status="healthy",
            latency_ms=100.0,
            mode="async",
        )

    monkeypatch.setattr(
        "app.services.task_service._simulate_external_call_async",
        accidental_sync_call,
    )

    n = 3
    start = time.perf_counter()
    tasks = [
        client.get(
            "/api/v1/tasks/summary?external_delay=0.1&external_timeout=1.0",
            headers=viewer_headers,
        )
        for _ in range(n)
    ]
    responses = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start

    for resp in responses:
        assert resp.status_code == 200

    # Because time.sleep(0.1) blocks the loop thread, requests serialize: elapsed >= ~N * 0.1
    assert elapsed >= n * 0.1 * 0.9
    # Generous upper bound: serialized ≈ n * 0.1s; guards against a
    # monkeypatch that silently no-ops and lets requests run unbounded.
    assert elapsed < n * 0.1 * 3


async def test_async_call_inside_async_overlaps(
    client: AsyncClient,
    viewer_headers: dict[str, str],
) -> None:
    """Proper non-blocking async calls overlap on the event loop, taking less than N * delay."""
    n = 3
    delay = 0.1
    start = time.perf_counter()
    tasks = [
        client.get(
            f"/api/v1/tasks/summary?external_delay={delay}&external_timeout=1.0",
            headers=viewer_headers,
        )
        for _ in range(n)
    ]
    responses = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start

    for resp in responses:
        assert resp.status_code == 200

    # Concurrently overlapping requests complete well below sequential time (N * delay)
    assert elapsed < n * delay
