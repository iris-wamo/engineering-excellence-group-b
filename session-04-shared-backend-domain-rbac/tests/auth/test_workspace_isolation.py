"""Tests for multi-tenancy and workspace isolation (Issue #72).

Proves that:
1. Projects and tasks belong to a workspace.
2. Cross-workspace access is blocked (users in one workspace cannot see or
   alter another workspace's data).
3. Access attempts across workspace boundaries return 404 Not Found to prevent leaking existence.
4. Accessing a workspace without membership returns 403 Forbidden.
5. Invalid/missing headers are safely handled with backward compatibility for existing data.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.contracts.constants import HEADER_WORKSPACE_ID

from app.models.enums import ProjectRole, TaskStatus
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.workspace_user import WorkspaceUser
from tests.conftest import AuthedUser, MakeUser


@pytest.fixture()
async def two_workspaces(db_session: AsyncSession) -> tuple[Workspace, Workspace]:
    """Create two separate workspaces for tenant isolation tests."""
    ws1 = await db_session.get(Workspace, 1)
    if ws1 is None:
        ws1 = Workspace(
            name="Acme Corp",
            slug="acme-corp",
            description="Primary tenant",
        )
        db_session.add(ws1)
        await db_session.commit()
        await db_session.refresh(ws1)

    ws2 = Workspace(
        name="Globex Corp",
        slug="globex-corp",
        description="Secondary tenant",
    )
    db_session.add(ws2)
    await db_session.commit()
    await db_session.refresh(ws2)
    return ws1, ws2


@pytest.fixture()
async def workspace_setup(
    db_session: AsyncSession,
    two_workspaces: tuple[Workspace, Workspace],
    make_user: MakeUser,
) -> dict:
    """Setup users, projects, and tasks across two isolated workspaces."""
    ws1, ws2 = two_workspaces

    # User 1: member only of Workspace 1 (admin in WS 1)
    user1 = await make_user("alice@acme.com")
    # User 2: member only of Workspace 2 (admin in WS 2)
    user2 = await make_user("bob@globex.com")
    # User 3: member of both Workspace 1 and Workspace 2
    user3 = await make_user("charlie@consultant.com")

    # User 2 is exclusively in Workspace 2 (remove default WS 1 membership, add WS 2)
    ws1_user2 = await db_session.get(WorkspaceUser, (ws1.id, user2.id))
    if ws1_user2 is not None:
        await db_session.delete(ws1_user2)
    db_session.add(WorkspaceUser(workspace_id=ws2.id, user_id=user2.id))

    # User 3 is in both Workspace 1 (already enrolled on signup) and Workspace 2
    db_session.add(WorkspaceUser(workspace_id=ws2.id, user_id=user3.id))

    # Project in Workspace 1
    p1 = Project(name="Acme Portal", slug="acme-portal", workspace_id=ws1.id)
    # Project in Workspace 2
    p2 = Project(name="Globex Engine", slug="globex-engine", workspace_id=ws2.id)
    db_session.add_all([p1, p2])
    await db_session.commit()
    await db_session.refresh(p1)
    await db_session.refresh(p2)

    # User 1 is admin in Project 1
    db_session.add(ProjectUser(project_id=p1.id, user_id=user1.id, role=ProjectRole.admin))
    # User 2 is admin in Project 2
    db_session.add(ProjectUser(project_id=p2.id, user_id=user2.id, role=ProjectRole.admin))

    # Tasks in Project 1 (Workspace 1)
    t1 = Task(
        title="Acme Task 1",
        project_id=p1.id,
        workspace_id=ws1.id,
        status=TaskStatus.todo,
        assignee_id=user1.id,
    )
    # Tasks in Project 2 (Workspace 2)
    t2 = Task(
        title="Globex Task 2",
        project_id=p2.id,
        workspace_id=ws2.id,
        status=TaskStatus.todo,
        assignee_id=user2.id,
    )
    db_session.add_all([t1, t2])
    await db_session.commit()
    await db_session.refresh(t1)
    await db_session.refresh(t2)

    return {
        "ws1": ws1,
        "ws2": ws2,
        "user1": user1,
        "user2": user2,
        "user3": user3,
        "p1": p1,
        "p2": p2,
        "t1": t1,
        "t2": t2,
    }


@pytest.mark.asyncio
async def test_projects_and_tasks_belong_to_workspace(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """Verify that projects and tasks have workspace_id correctly assigned."""
    p1 = workspace_setup["p1"]
    p2 = workspace_setup["p2"]
    t1 = workspace_setup["t1"]
    t2 = workspace_setup["t2"]

    assert p1.workspace_id == workspace_setup["ws1"].id
    assert p2.workspace_id == workspace_setup["ws2"].id
    assert t1.workspace_id == workspace_setup["ws1"].id
    assert t2.workspace_id == workspace_setup["ws2"].id


@pytest.mark.asyncio
async def test_cross_workspace_project_get_blocked(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """User in Workspace 1 attempting to GET a project in Workspace 2 receives 404."""
    user1: AuthedUser = workspace_setup["user1"]
    p2: Project = workspace_setup["p2"]

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(workspace_setup["ws1"].id),
    }

    # User 1 queries project 2 while in workspace 1 context
    res = await client.get(f"/api/v1/projects/{p2.id}", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "Project not found"


@pytest.mark.asyncio
async def test_cross_workspace_project_listing_isolated(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """Listing projects in Workspace 1 only returns Workspace 1 projects."""
    user1: AuthedUser = workspace_setup["user1"]
    ws1: Workspace = workspace_setup["ws1"]

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(ws1.id),
    }

    res = await client.get("/api/v1/projects", headers=headers)
    assert res.status_code == 200
    items = res.json()["items"]
    project_names = [item["name"] for item in items]

    assert "Acme Portal" in project_names
    assert "Globex Engine" not in project_names


@pytest.mark.asyncio
async def test_cross_workspace_task_get_blocked(client: AsyncClient, workspace_setup: dict) -> None:
    """User in Workspace 1 attempting to GET a task in Workspace 2 receives 404."""
    user1: AuthedUser = workspace_setup["user1"]
    t2: Task = workspace_setup["t2"]

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(workspace_setup["ws1"].id),
    }

    res = await client.get(f"/api/v1/tasks/{t2.id}", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "Task not found"


@pytest.mark.asyncio
async def test_cross_workspace_task_listing_isolated(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """Listing tasks in Workspace 1 only returns Workspace 1 tasks."""
    user1: AuthedUser = workspace_setup["user1"]
    ws1: Workspace = workspace_setup["ws1"]

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(ws1.id),
    }

    res = await client.get("/api/v1/tasks", headers=headers)
    assert res.status_code == 200
    items = res.json()["items"]
    task_titles = [item["title"] for item in items]

    assert "Acme Task 1" in task_titles
    assert "Globex Task 2" not in task_titles


@pytest.mark.asyncio
async def test_cross_workspace_task_creation_blocked(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """Cannot create a task pointing to a project from a different workspace."""
    user1: AuthedUser = workspace_setup["user1"]
    p2: Project = workspace_setup["p2"]
    ws1: Workspace = workspace_setup["ws1"]

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(ws1.id),
    }

    # Attempt to create task in project 2 (which is in Workspace 2) using Workspace 1 context
    res = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Malicious Cross-Tenant Task",
            "project_id": p2.id,
        },
    )
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "Project not found"


@pytest.mark.asyncio
async def test_cross_workspace_status_update_blocked(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """User in Workspace 1 cannot update the status of a task in Workspace 2."""
    user1: AuthedUser = workspace_setup["user1"]
    t2: Task = workspace_setup["t2"]
    ws1: Workspace = workspace_setup["ws1"]

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(ws1.id),
    }

    res = await client.patch(
        f"/api/v1/tasks/{t2.id}/status",
        headers=headers,
        json={"status": "in_progress"},
    )
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "Task not found"


@pytest.mark.asyncio
async def test_cross_workspace_task_assign_blocked(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """User in Workspace 1 cannot assign a task belonging to Workspace 2."""
    user1: AuthedUser = workspace_setup["user1"]
    t2: Task = workspace_setup["t2"]
    ws1: Workspace = workspace_setup["ws1"]

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(ws1.id),
    }

    res = await client.post(
        f"/api/v1/tasks/{t2.id}/assign",
        headers=headers,
        json={"assignee_id": user1.id, "assigned_by_id": user1.id},
    )
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "Task not found"


@pytest.mark.asyncio
async def test_user_cannot_switch_to_unauthorized_workspace(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """User 1 (only a member of Workspace 1) is rejected when claiming Workspace 2 header."""
    user1: AuthedUser = workspace_setup["user1"]
    ws2: Workspace = workspace_setup["ws2"]

    # User 1 provides X-Workspace-ID: ws2.id
    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(ws2.id),
    }

    res = await client.get("/api/v1/projects", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"
    assert "not have permission to access this workspace" in res.json()["error"]["message"]


@pytest.mark.asyncio
async def test_invalid_and_nonexistent_workspace_headers(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """Malformed and non-existent workspace headers return proper error envelopes."""
    user1: AuthedUser = workspace_setup["user1"]

    # 1. Non-integer header -> 400
    res = await client.get(
        "/api/v1/projects",
        headers={**user1.headers, HEADER_WORKSPACE_ID: "abc-invalid"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_WORKSPACE_ID"

    # 2. Negative integer -> 400
    res = await client.get(
        "/api/v1/projects",
        headers={**user1.headers, HEADER_WORKSPACE_ID: "-5"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_WORKSPACE_ID"

    # 3. Non-existent workspace ID -> 404
    res = await client.get(
        "/api/v1/projects",
        headers={**user1.headers, HEADER_WORKSPACE_ID: "999999"},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_multi_workspace_user_can_switch_context(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """User 3 (member of both workspaces) can switch context and see respective data."""
    user3: AuthedUser = workspace_setup["user3"]
    ws1: Workspace = workspace_setup["ws1"]
    ws2: Workspace = workspace_setup["ws2"]

    # When querying in Workspace 1
    res1 = await client.get(
        "/api/v1/projects",
        headers={**user3.headers, HEADER_WORKSPACE_ID: str(ws1.id)},
    )
    assert res1.status_code == 200
    names1 = [p["name"] for p in res1.json()["items"]]
    assert "Acme Portal" in names1
    assert "Globex Engine" not in names1

    # When querying in Workspace 2
    res2 = await client.get(
        "/api/v1/projects",
        headers={**user3.headers, HEADER_WORKSPACE_ID: str(ws2.id)},
    )
    assert res2.status_code == 200
    names2 = [p["name"] for p in res2.json()["items"]]
    assert "Globex Engine" in names2
    assert "Acme Portal" not in names2


@pytest.mark.asyncio
async def test_backward_compatibility_default_workspace(
    client: AsyncClient, workspace_setup: dict
) -> None:
    """Requests without X-Workspace-ID default to Workspace 1 and work seamlessly."""
    user1: AuthedUser = workspace_setup["user1"]

    # No X-Workspace-ID header passed
    res = await client.get("/api/v1/projects", headers=user1.headers)
    assert res.status_code == 200
    names = [p["name"] for p in res.json()["items"]]
    assert "Acme Portal" in names
