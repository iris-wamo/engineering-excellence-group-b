"""Invalid-case tests: requests the API must refuse, and how it says no.

Each test checks the status code and the error code from the standard envelope,
because clients branch on the code rather than the message.
"""

import pytest
from httpx import AsyncClient

from app.models.enums import ProjectRole, TaskStatus
from tests.fixtures.factories import MISSING_ID, DataFactory


def _error_code(body: dict) -> str:
    return str(body["error"]["code"])


# --- Request validation (422) ---


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"status": "archived"},
        {"priority": "urgent"},
    ],
    ids=["page-zero", "page-size-zero", "page-size-over-max", "unknown-status", "unknown-priority"],
)
async def test_list_tasks_rejects_bad_query(
    client: AsyncClient, viewer_headers: dict[str, str], params: dict
) -> None:
    response = await client.get("/api/v1/tasks", params=params, headers=viewer_headers)

    assert response.status_code == 422
    assert _error_code(response.json()) == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "payload",
    [
        {"project_id": 1},
        {"title": "   ", "project_id": 1},
        {"title": "No project"},
        {"title": "Bad priority", "project_id": 1, "priority": "urgent"},
        {"title": "Bad date", "project_id": 1, "due_date": "not-a-date"},
    ],
    ids=["missing-title", "blank-title", "missing-project", "bad-priority", "bad-due-date"],
)
async def test_create_task_rejects_invalid_payload(
    client: AsyncClient, viewer_headers: dict[str, str], payload: dict
) -> None:
    response = await client.post("/api/v1/tasks", json=payload, headers=viewer_headers)

    assert response.status_code == 422
    assert _error_code(response.json()) == "VALIDATION_ERROR"


async def test_status_update_rejects_unknown_status(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    dev = await factory.member(project)
    task = await factory.task(project, assignee=dev.id)

    response = await client.patch(
        f"/api/v1/tasks/{task.id}/status", json={"status": "archived"}, headers=dev.headers
    )

    assert response.status_code == 422
    assert _error_code(response.json()) == "VALIDATION_ERROR"


async def test_get_project_rejects_non_positive_id(
    client: AsyncClient, viewer_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/projects/0", headers=viewer_headers)

    assert response.status_code == 422
    assert _error_code(response.json()) == "VALIDATION_ERROR"


# --- Missing targets (404) ---


async def test_get_missing_project_returns_404(
    client: AsyncClient, viewer_headers: dict[str, str]
) -> None:
    response = await client.get(f"/api/v1/projects/{MISSING_ID}", headers=viewer_headers)

    assert response.status_code == 404
    assert _error_code(response.json()) == "NOT_FOUND"


async def test_create_task_in_missing_project_returns_404(
    client: AsyncClient, viewer_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/tasks", json={"title": "Orphan", "project_id": MISSING_ID}, headers=viewer_headers
    )

    assert response.status_code == 404
    assert _error_code(response.json()) == "NOT_FOUND"


async def test_create_task_for_missing_assignee_returns_404(
    client: AsyncClient, factory: DataFactory, viewer_headers: dict[str, str]
) -> None:
    project = await factory.project()

    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Ghost work", "project_id": project.id, "assignee_id": MISSING_ID},
        headers=viewer_headers,
    )

    assert response.status_code == 404
    assert _error_code(response.json()) == "NOT_FOUND"


async def test_status_update_on_missing_task_returns_404(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    dev = await factory.member(project)

    response = await client.patch(
        f"/api/v1/tasks/{MISSING_ID}/status", json={"status": "in_progress"}, headers=dev.headers
    )

    assert response.status_code == 404
    assert _error_code(response.json()) == "NOT_FOUND"


async def test_assign_to_missing_user_returns_404(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    lead = await factory.member(project, ProjectRole.manager)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign", json={"assignee_id": MISSING_ID}, headers=lead.headers
    )

    assert response.status_code == 404
    assert _error_code(response.json()) == "NOT_FOUND"


# --- Business rule violations ---


async def test_assign_to_user_outside_the_project_is_rejected(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    lead = await factory.member(project, ProjectRole.manager)
    outsider = await factory.user()
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign", json={"assignee_id": outsider.id}, headers=lead.headers
    )

    assert response.status_code == 400
    assert _error_code(response.json()) == "PROJECT_MEMBERSHIP_REQUIRED"


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (TaskStatus.todo, TaskStatus.review),
        (TaskStatus.todo, TaskStatus.done),
        (TaskStatus.done, TaskStatus.todo),
    ],
    ids=["todo-to-review", "todo-to-done", "done-to-todo"],
)
async def test_skipping_workflow_steps_is_rejected(
    client: AsyncClient, factory: DataFactory, start: TaskStatus, target: TaskStatus
) -> None:
    project = await factory.project()
    dev = await factory.member(project)
    task = await factory.task(project, assignee=dev.id, status=start)

    response = await client.patch(
        f"/api/v1/tasks/{task.id}/status", json={"status": target.value}, headers=dev.headers
    )

    assert response.status_code == 400
    assert _error_code(response.json()) == "INVALID_STATUS_TRANSITION"


async def test_duplicate_project_name_in_same_workspace_conflicts(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    admin = await factory.member(project, ProjectRole.admin)
    first = await client.post("/api/v1/projects", json={"name": "Payments"}, headers=admin.headers)
    assert first.status_code == 201

    response = await client.post(
        "/api/v1/projects", json={"name": "Payments"}, headers=admin.headers
    )

    assert response.status_code == 409
    assert _error_code(response.json()) == "CONFLICT"
