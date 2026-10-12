"""Tests for multi-tenancy and workspace isolation (Issue #72).

Proves that:
1. Projects and tasks belong to a workspace.
2. Cross-workspace access is blocked (users in one workspace cannot see or
   alter another workspace's data).
3. Access attempts across workspace boundaries return 404 Not Found to prevent leaking existence.
4. Accessing a workspace without membership returns 403 Forbidden.
5. Invalid/missing headers are safely handled with backward compatibility for existing data.
"""

from typing import NamedTuple

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.contracts.constants import HEADER_WORKSPACE_ID

from app.models.enums import ProjectRole
from app.models.project import Project
from app.models.task import Task
from app.models.workspace import Workspace
from tests.fixtures.auth import AuthedUser, auth_headers_for
from tests.fixtures.factories import DataFactory


class WorkspaceSetup(NamedTuple):
    """What the workspace_setup fixture creates. See its docstring for who belongs where."""

    ws1: Workspace
    ws2: Workspace
    user1: AuthedUser
    user2: AuthedUser
    user3: AuthedUser
    p1: Project
    p2: Project
    t1: Task
    t2: Task


@pytest.fixture()
async def workspace_setup(db_session: AsyncSession, factory: DataFactory) -> WorkspaceSetup:
    """Two tenants with their own admin, project, and task, plus one user in both.

    - user1 (alice) belongs only to Workspace 1 and is admin of p1
    - user2 (bob) belongs only to Workspace 2 and is admin of p2
    - user3 (charlie) belongs to both workspaces and holds no role
    """
    ws1 = await db_session.get(Workspace, 1)
    assert ws1 is not None
    ws2 = await factory.workspace(name="Globex Corp", slug="globex-corp")

    alice = await factory.user(email="alice@acme.com", workspace_ids=(ws1.id,))
    bob = await factory.user(email="bob@globex.com", workspace_ids=(ws2.id,))
    charlie = await factory.user(email="charlie@consultant.com", workspace_ids=(ws1.id, ws2.id))

    p1 = await factory.project(name="Acme Portal", slug="acme-portal", workspace=ws1)
    p2 = await factory.project(name="Globex Engine", slug="globex-engine", workspace=ws2)
    await factory.grant_role(alice, p1, ProjectRole.admin)
    await factory.grant_role(bob, p2, ProjectRole.admin)

    t1 = await factory.task(p1, title="Acme Task 1", assignee=alice)
    t2 = await factory.task(p2, title="Globex Task 2", assignee=bob)

    # Headers carry no X-Workspace-ID, so each test chooses the workspace explicitly.
    return WorkspaceSetup(
        ws1=ws1,
        ws2=ws2,
        user1=AuthedUser(alice.id, auth_headers_for(alice.id)),
        user2=AuthedUser(bob.id, auth_headers_for(bob.id)),
        user3=AuthedUser(charlie.id, auth_headers_for(charlie.id)),
        p1=p1,
        p2=p2,
        t1=t1,
        t2=t2,
    )


async def test_projects_and_tasks_belong_to_workspace(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """Verify that projects and tasks have workspace_id correctly assigned."""
    p1 = workspace_setup.p1
    p2 = workspace_setup.p2
    t1 = workspace_setup.t1
    t2 = workspace_setup.t2

    assert p1.workspace_id == workspace_setup.ws1.id
    assert p2.workspace_id == workspace_setup.ws2.id
    assert t1.workspace_id == workspace_setup.ws1.id
    assert t2.workspace_id == workspace_setup.ws2.id


async def test_cross_workspace_project_get_blocked(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """User in Workspace 1 attempting to GET a project in Workspace 2 receives 404."""
    user1: AuthedUser = workspace_setup.user1
    p2: Project = workspace_setup.p2

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(workspace_setup.ws1.id),
    }

    # User 1 queries project 2 while in workspace 1 context
    res = await client.get(f"/api/v1/projects/{p2.id}", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "Project not found"


async def test_cross_workspace_project_listing_isolated(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """Listing projects in Workspace 1 only returns Workspace 1 projects."""
    user1: AuthedUser = workspace_setup.user1
    ws1: Workspace = workspace_setup.ws1

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


async def test_cross_workspace_task_get_blocked(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """User in Workspace 1 attempting to GET a task in Workspace 2 receives 404."""
    user1: AuthedUser = workspace_setup.user1
    t2: Task = workspace_setup.t2

    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(workspace_setup.ws1.id),
    }

    res = await client.get(f"/api/v1/tasks/{t2.id}", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["message"] == "Task not found"


async def test_cross_workspace_task_listing_isolated(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """Listing tasks in Workspace 1 only returns Workspace 1 tasks."""
    user1: AuthedUser = workspace_setup.user1
    ws1: Workspace = workspace_setup.ws1

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


async def test_cross_workspace_task_creation_blocked(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """Cannot create a task pointing to a project from a different workspace."""
    user1: AuthedUser = workspace_setup.user1
    p2: Project = workspace_setup.p2
    ws1: Workspace = workspace_setup.ws1

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


async def test_cross_workspace_status_update_blocked(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """User in Workspace 1 cannot update the status of a task in Workspace 2."""
    user1: AuthedUser = workspace_setup.user1
    t2: Task = workspace_setup.t2
    ws1: Workspace = workspace_setup.ws1

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


async def test_cross_workspace_task_assign_blocked(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """User in Workspace 1 cannot assign a task belonging to Workspace 2."""
    user1: AuthedUser = workspace_setup.user1
    t2: Task = workspace_setup.t2
    ws1: Workspace = workspace_setup.ws1

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


async def test_user_cannot_switch_to_unauthorized_workspace(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """User 1 (only a member of Workspace 1) is rejected when claiming Workspace 2 header."""
    user1: AuthedUser = workspace_setup.user1
    ws2: Workspace = workspace_setup.ws2

    # User 1 provides X-Workspace-ID: ws2.id
    headers = {
        **user1.headers,
        HEADER_WORKSPACE_ID: str(ws2.id),
    }

    res = await client.get("/api/v1/projects", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"
    assert "not have permission to access this workspace" in res.json()["error"]["message"]


async def test_invalid_and_nonexistent_workspace_headers(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """Malformed and non-existent workspace headers return proper error envelopes."""
    user1: AuthedUser = workspace_setup.user1

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


async def test_multi_workspace_user_can_switch_context(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """User 3 (member of both workspaces) can switch context and see respective data."""
    user3: AuthedUser = workspace_setup.user3
    ws1: Workspace = workspace_setup.ws1
    ws2: Workspace = workspace_setup.ws2

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


async def test_backward_compatibility_default_workspace(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """Requests without X-Workspace-ID default to Workspace 1 and work seamlessly."""
    user1: AuthedUser = workspace_setup.user1

    # No X-Workspace-ID header passed
    res = await client.get("/api/v1/projects", headers=user1.headers)
    assert res.status_code == 200
    names = [p["name"] for p in res.json()["items"]]
    assert "Acme Portal" in names


async def test_admin_role_does_not_bleed_across_workspaces(
    client: AsyncClient, workspace_setup: WorkspaceSetup, factory: DataFactory
) -> None:
    """User 3 is a member in both WS 1 & WS 2, and an admin in a WS 1 project,
    but holds NO admin role in WS 2. Attempting to create a project in WS 2 returns 403 Forbidden.
    """
    user3: AuthedUser = workspace_setup.user3
    p1: Project = workspace_setup.p1
    ws2: Workspace = workspace_setup.ws2

    # Make user3 an admin in Project 1 (Workspace 1)
    await factory.grant_role(user3.id, p1, ProjectRole.admin)

    # User 3 tries to create a project in Workspace 2 where they hold no admin role
    res = await client.post(
        "/api/v1/projects",
        headers={**user3.headers, HEADER_WORKSPACE_ID: str(ws2.id)},
        json={"name": "Unauthorized Project in WS2", "description": "Should fail"},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"


async def test_cross_workspace_raw_task_import_blocked(
    client: AsyncClient, workspace_setup: WorkspaceSetup
) -> None:
    """Importing a task with a project belonging to another workspace fails normalization."""
    user1: AuthedUser = workspace_setup.user1
    p2: Project = workspace_setup.p2
    ws1: Workspace = workspace_setup.ws1

    res = await client.post(
        "/api/v1/tasks/import",
        headers={**user1.headers, HEADER_WORKSPACE_ID: str(ws1.id)},
        json={
            "raw_payload": {
                "summary": "Import into foreign project",
                "project_id": p2.id,
            }
        },
    )
    assert res.status_code == 422
    body = res.json()
    assert body["status"] == "FAILED"
    assert "not found" in body["error_details"]["message"].lower()


async def test_same_slug_allowed_in_different_workspaces(
    client: AsyncClient, workspace_setup: WorkspaceSetup, db_session: AsyncSession
) -> None:
    """Projects in different workspaces can share the same slug without conflict."""
    user1: AuthedUser = workspace_setup.user1
    user2: AuthedUser = workspace_setup.user2
    ws1: Workspace = workspace_setup.ws1
    ws2: Workspace = workspace_setup.ws2

    # Create project 'Alpha Ops' in Workspace 1
    res1 = await client.post(
        "/api/v1/projects",
        headers={**user1.headers, HEADER_WORKSPACE_ID: str(ws1.id)},
        json={"name": "Alpha Ops", "description": "WS1 Ops"},
    )
    assert res1.status_code == 201

    # Create project 'Alpha Ops' in Workspace 2 (same slug 'alpha-ops')
    res2 = await client.post(
        "/api/v1/projects",
        headers={**user2.headers, HEADER_WORKSPACE_ID: str(ws2.id)},
        json={"name": "Alpha Ops", "description": "WS2 Ops"},
    )
    assert res2.status_code == 201

    p_ws1 = await db_session.get(Project, res1.json()["id"])
    p_ws2 = await db_session.get(Project, res2.json()["id"])
    assert p_ws1 is not None and p_ws2 is not None
    assert p_ws1.slug == p_ws2.slug == "alpha-ops"
    assert p_ws1.workspace_id == ws1.id
    assert p_ws2.workspace_id == ws2.id

    # Duplicate in SAME workspace returns 409 Conflict
    res3 = await client.post(
        "/api/v1/projects",
        headers={**user1.headers, HEADER_WORKSPACE_ID: str(ws1.id)},
        json={"name": "Alpha Ops", "description": "Duplicate in WS1"},
    )
    assert res3.status_code == 409
    assert res3.json()["error"]["code"] == "CONFLICT"


async def test_anonymous_default_workspace_setting_toggle(
    client: AsyncClient,
) -> None:
    """When allow_anonymous_default_workspace is False, unauthenticated requests
    without header get 401."""
    from unittest.mock import patch

    from app.core.config import settings

    with patch.object(settings, "allow_anonymous_default_workspace", False):
        res = await client.get("/api/v1/projects")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHENTICATED"
