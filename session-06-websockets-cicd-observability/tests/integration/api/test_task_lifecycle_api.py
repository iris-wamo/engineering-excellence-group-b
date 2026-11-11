"""Integration tests for API behavior across endpoints: a task's full life inside a
tenant workspace, and the task list filters.

Setup that the API cannot do yet (roles, workspaces, starting statuses) comes from the
`factory` fixture. Everything the test asserts on goes through HTTP.
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole, TaskPriority, TaskStatus
from app.models.project import Project
from tests.fixtures.auth import auth_headers_for
from tests.fixtures.factories import DataFactory


async def test_task_lifecycle_inside_a_tenant_workspace(
    client: AsyncClient, db_session: AsyncSession, factory: DataFactory
) -> None:
    """Admin creates a project, a manager assigns a task, the assignee walks it to done."""
    workspace = await factory.workspace(name="Initech")
    # The first admin has to be seeded: no endpoint can grant a role yet.
    bootstrap = await factory.project(workspace=workspace)
    admin = await factory.member(bootstrap, ProjectRole.admin)

    created = await client.post("/api/v1/projects", json={"name": "Launch"}, headers=admin.headers)
    assert created.status_code == 201
    project = await db_session.scalar(select(Project).where(Project.id == created.json()["id"]))
    assert project is not None
    assert project.workspace_id == workspace.id

    lead = await factory.member(project, ProjectRole.manager)
    dev = await factory.member(project, ProjectRole.member)

    task = await client.post(
        "/api/v1/tasks",
        json={"title": "Ship it", "project_id": project.id, "priority": "high"},
        headers=lead.headers,
    )
    assert task.status_code == 201
    task_id = task.json()["id"]

    assigned = await client.post(
        f"/api/v1/tasks/{task_id}/assign",
        json={"assignee_id": dev.id},
        headers=lead.headers,
    )
    assert assigned.status_code == 200
    assert assigned.json()["assignee_id"] == dev.id

    for status in ("in_progress", "review", "done"):
        moved = await client.patch(
            f"/api/v1/tasks/{task_id}/status", json={"status": status}, headers=dev.headers
        )
        assert moved.status_code == 200, moved.json()

    final = await client.get(f"/api/v1/tasks/{task_id}", headers=dev.headers)
    assert final.status_code == 200
    assert final.json()["status"] == "done"
    assert final.json()["assignee_id"] == dev.id

    done = await client.get("/api/v1/tasks", params={"status": "done"}, headers=dev.headers)
    assert [item["id"] for item in done.json()["items"]] == [task_id]


async def test_list_tasks_filters_combine(client: AsyncClient, factory: DataFactory) -> None:
    alpha = await factory.project(name="Alpha")
    beta = await factory.project(name="Beta")
    dev = await factory.user()
    doing, high = TaskStatus.in_progress, TaskPriority.high
    wanted = await factory.task(alpha, assignee=dev, status=doing, priority=high)
    # One near-miss per filter, so each filter has to do its job.
    await factory.task(alpha, assignee=dev, status=TaskStatus.todo, priority=high)
    await factory.task(alpha, assignee=dev, status=doing, priority=TaskPriority.low)
    await factory.task(alpha, status=doing, priority=high)
    await factory.task(beta, assignee=dev, status=doing, priority=high)

    response = await client.get(
        "/api/v1/tasks",
        params={
            "status": "in_progress",
            "priority": "high",
            "project_id": alpha.id,
            "assignee_id": dev.id,
        },
        headers=auth_headers_for(dev.id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [wanted.id]


async def test_list_tasks_paginates_newest_first(
    client: AsyncClient, factory: DataFactory, viewer_headers: dict[str, str]
) -> None:
    project = await factory.project()
    tasks = [await factory.task(project) for _ in range(5)]
    newest_first = [task.id for task in reversed(tasks)]

    async def page(number: int) -> dict[str, Any]:
        params = {"page": number, "page_size": 2}
        response = await client.get("/api/v1/tasks", params=params, headers=viewer_headers)
        body: dict[str, Any] = response.json()
        return body

    page1, page3 = await page(1), await page(3)

    assert page1["total"] == 5
    assert [item["id"] for item in page1["items"]] == newest_first[:2]
    assert [item["id"] for item in page3["items"]] == newest_first[4:]


async def test_list_tasks_page_past_the_end_is_empty(
    client: AsyncClient, factory: DataFactory, viewer_headers: dict[str, str]
) -> None:
    project = await factory.project()
    await factory.task(project)

    params = {"page": 5, "page_size": 10}
    body = (await client.get("/api/v1/tasks", params=params, headers=viewer_headers)).json()

    assert body["total"] == 1
    assert body["items"] == []


async def test_list_projects_search_is_case_insensitive(
    client: AsyncClient, factory: DataFactory, viewer_headers: dict[str, str]
) -> None:
    await factory.project(name="Billing Service")
    await factory.project(name="Search API")

    params = {"search": "billing"}
    body = (await client.get("/api/v1/projects", params=params, headers=viewer_headers)).json()

    assert [item["name"] for item in body["items"]] == ["Billing Service"]
