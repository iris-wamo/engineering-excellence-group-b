import pytest
from httpx import AsyncClient

from app.models.enums import ProjectRole
from tests.fixtures.auth import auth_headers_for
from tests.fixtures.factories import MISSING_ID, DataFactory


def _error_code(body: dict) -> str:
    return str(body["error"]["code"])


async def test_project_member_can_create_a_comment(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "This task is almost complete."},
        headers=member.headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"] == task.id
    assert body["user_id"] == member.id
    assert body["content"] == "This task is almost complete."
    assert body["id"] > 0
    assert body["created_at"]


async def test_comment_author_is_the_caller_not_the_request_body(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    member = await factory.member(project)
    other = await factory.member(project)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "Mine, not theirs.", "user_id": other.id},
        headers=member.headers,
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == member.id


@pytest.mark.parametrize(
    "role",
    [ProjectRole.member, ProjectRole.owner, ProjectRole.manager, ProjectRole.admin],
)
async def test_every_project_role_may_comment(
    client: AsyncClient, factory: DataFactory, role: ProjectRole
) -> None:
    project = await factory.project()
    member = await factory.member(project, role)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": f"Comment from a {role.value}."},
        headers=member.headers,
    )

    assert response.status_code == 201


async def test_project_member_can_read_task_comments(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    author = await factory.member(project)
    reader = await factory.member(project)
    task = await factory.task(project)
    first = await factory.comment(task, author.id, content="First")
    second = await factory.comment(task, author.id, content="Second")

    response = await client.get(f"/api/v1/tasks/{task.id}/comments", headers=reader.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert [item["id"] for item in body["items"]] == [second.id, first.id]
    assert body["items"][0]["content"] == "Second"
    assert body["items"][0]["user_id"] == author.id


async def test_comments_are_listed_per_task(client: AsyncClient, factory: DataFactory) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)
    other_task = await factory.task(project)
    await factory.comment(task, member.id, content="On the task under test")
    await factory.comment(other_task, member.id, content="On another task")

    response = await client.get(f"/api/v1/tasks/{task.id}/comments", headers=member.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["content"] == "On the task under test"


async def test_comment_listing_is_paginated(client: AsyncClient, factory: DataFactory) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)
    for index in range(3):
        await factory.comment(task, member.id, content=f"Comment {index}")

    response = await client.get(
        f"/api/v1/tasks/{task.id}/comments",
        params={"page": 2, "page_size": 2},
        headers=member.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["page_size"], body["total_pages"]) == (3, 2, 2, 2)
    assert len(body["items"]) == 1


async def test_a_task_without_comments_lists_nothing(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)

    response = await client.get(f"/api/v1/tasks/{task.id}/comments", headers=member.headers)

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 10,
        "total_pages": 0,
    }


async def test_non_member_cannot_create_a_comment(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    task = await factory.task(project)
    outsider = await factory.user()  # in the workspace, but holds no role in the project

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "Let me in."},
        headers=auth_headers_for(outsider.id, workspace_id=project.workspace_id),
    )

    assert response.status_code == 403
    assert _error_code(response.json()) == "FORBIDDEN"


async def test_non_member_cannot_read_comments(client: AsyncClient, factory: DataFactory) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)
    await factory.comment(task, member.id)
    outsider = await factory.user()

    response = await client.get(
        f"/api/v1/tasks/{task.id}/comments",
        headers=auth_headers_for(outsider.id, workspace_id=project.workspace_id),
    )

    assert response.status_code == 403
    assert _error_code(response.json()) == "FORBIDDEN"


async def test_member_of_another_project_is_refused(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    other_project = await factory.project()
    outsider = await factory.member(other_project)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "Wrong project."},
        headers=outsider.headers,
    )

    assert response.status_code == 403


async def test_unauthenticated_request_is_refused(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    task = await factory.task(project)

    response = await client.get(f"/api/v1/tasks/{task.id}/comments")

    assert response.status_code == 401


async def test_user_from_another_workspace_cannot_read_comments(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)
    await factory.comment(task, member.id, content="Tenant 1 only")

    other_workspace = await factory.workspace()
    other_project = await factory.project(workspace=other_workspace)
    stranger = await factory.member(other_project, ProjectRole.admin)

    response = await client.get(f"/api/v1/tasks/{task.id}/comments", headers=stranger.headers)

    assert response.status_code == 404
    assert _error_code(response.json()) == "NOT_FOUND"


async def test_user_from_another_workspace_cannot_comment(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    task = await factory.task(project)

    other_workspace = await factory.workspace()
    other_project = await factory.project(workspace=other_workspace)
    stranger = await factory.member(other_project, ProjectRole.admin)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "Crossing the boundary."},
        headers=stranger.headers,
    )

    assert response.status_code == 404


async def test_claiming_another_workspace_is_refused(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    task = await factory.task(project)
    other_workspace = await factory.workspace()
    other_project = await factory.project(workspace=other_workspace)
    stranger = await factory.member(other_project)

    response = await client.get(
        f"/api/v1/tasks/{task.id}/comments",
        headers=auth_headers_for(stranger.id, workspace_id=project.workspace_id),
    )

    assert response.status_code == 403


async def test_commenting_on_a_missing_task_is_not_found(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    member = await factory.member(project)

    response = await client.post(
        f"/api/v1/tasks/{MISSING_ID}/comments",
        json={"content": "Nobody home."},
        headers=member.headers,
    )

    assert response.status_code == 404
    assert _error_code(response.json()) == "NOT_FOUND"


async def test_listing_comments_of_a_missing_task_is_not_found(
    client: AsyncClient, factory: DataFactory
) -> None:
    project = await factory.project()
    member = await factory.member(project)

    response = await client.get(f"/api/v1/tasks/{MISSING_ID}/comments", headers=member.headers)

    assert response.status_code == 404


async def test_non_numeric_task_id_is_rejected(
    client: AsyncClient, viewer_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/tasks/not-a-number/comments", headers=viewer_headers)

    assert response.status_code == 422
    assert _error_code(response.json()) == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "payload",
    [{}, {"content": ""}, {"content": "   "}, {"content": "x" * 2001}, {"content": 7}],
    ids=["missing", "empty", "blank", "too-long", "not-a-string"],
)
async def test_create_comment_rejects_invalid_payload(
    client: AsyncClient, factory: DataFactory, payload: dict
) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments", json=payload, headers=member.headers
    )

    assert response.status_code == 422
    assert _error_code(response.json()) == "VALIDATION_ERROR"


async def test_comment_content_is_trimmed(client: AsyncClient, factory: DataFactory) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "  Trim me.  "},
        headers=member.headers,
    )

    assert response.status_code == 201
    assert response.json()["content"] == "Trim me."


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 0}, {"page_size": 101}],
    ids=["page-zero", "page-size-zero", "page-size-over-max"],
)
async def test_list_comments_rejects_bad_query(
    client: AsyncClient, factory: DataFactory, params: dict
) -> None:
    project = await factory.project()
    member = await factory.member(project)
    task = await factory.task(project)

    response = await client.get(
        f"/api/v1/tasks/{task.id}/comments", params=params, headers=member.headers
    )

    assert response.status_code == 422
    assert _error_code(response.json()) == "VALIDATION_ERROR"
