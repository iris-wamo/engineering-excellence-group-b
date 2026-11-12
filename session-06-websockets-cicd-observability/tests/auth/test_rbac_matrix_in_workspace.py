"""The full RBAC matrix, end to end, inside a tenant workspace other than Workspace 1.

test_rbac_api.py walks the matrix row by row in the default workspace. This module runs
every role against every role-gated endpoint in a separate workspace, so the matrix is
shown to hold once tenancy is involved too. `None` is a workspace member with no role.
"""

import pytest
from httpx import AsyncClient

from app.models.enums import ProjectRole
from app.models.project import Project
from tests.fixtures.auth import AuthedUser, auth_headers_for
from tests.fixtures.factories import DataFactory

ROLES = [ProjectRole.admin, ProjectRole.manager, ProjectRole.owner, ProjectRole.member, None]


@pytest.fixture()
async def tenant_project(factory: DataFactory) -> Project:
    workspace = await factory.workspace(name="Tenant")
    return await factory.project(name="Tenant Project", workspace=workspace)


async def _caller(factory: DataFactory, project: Project, role: ProjectRole | None) -> AuthedUser:
    if role is not None:
        return await factory.member(project, role)
    user = await factory.user(workspace_ids=(project.workspace_id,))
    return AuthedUser(user.id, auth_headers_for(user.id, workspace_id=project.workspace_id))


def _expected(role: ProjectRole | None, allowed: set[ProjectRole], ok: int) -> int:
    return ok if role in allowed else 403


@pytest.mark.parametrize("role", ROLES, ids=lambda r: r or "no-role")
async def test_create_project(
    client: AsyncClient, factory: DataFactory, tenant_project: Project, role: ProjectRole | None
) -> None:
    caller = await _caller(factory, tenant_project, role)

    response = await client.post(
        "/api/v1/projects", json={"name": "Matrix Project"}, headers=caller.headers
    )

    assert response.status_code == _expected(role, {ProjectRole.admin}, 201)


@pytest.mark.parametrize("role", ROLES, ids=lambda r: r or "no-role")
async def test_create_user(
    client: AsyncClient, factory: DataFactory, tenant_project: Project, role: ProjectRole | None
) -> None:
    caller = await _caller(factory, tenant_project, role)

    response = await client.post(
        "/api/v1/users",
        json={"name": "New Hire", "email": "new-hire@example.com"},
        headers=caller.headers,
    )

    assert response.status_code == _expected(role, {ProjectRole.admin}, 201)


@pytest.mark.parametrize("role", ROLES, ids=lambda r: r or "no-role")
async def test_assign_task(
    client: AsyncClient, factory: DataFactory, tenant_project: Project, role: ProjectRole | None
) -> None:
    caller = await _caller(factory, tenant_project, role)
    dev = await factory.member(tenant_project, ProjectRole.member)
    task = await factory.task(tenant_project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign", json={"assignee_id": dev.id}, headers=caller.headers
    )

    allowed = {ProjectRole.admin, ProjectRole.manager, ProjectRole.owner}
    assert response.status_code == _expected(role, allowed, 200)


@pytest.mark.parametrize("role", ROLES, ids=lambda r: r or "no-role")
async def test_only_the_assignee_moves_a_task(
    client: AsyncClient, factory: DataFactory, tenant_project: Project, role: ProjectRole | None
) -> None:
    """Status is an ownership check: every role may move its own task and no one else's."""
    caller = await _caller(factory, tenant_project, role)
    own = await factory.task(tenant_project, assignee=caller.id)
    colleague = await factory.member(tenant_project, ProjectRole.member)
    others = await factory.task(tenant_project, assignee=colleague.id)

    own_move = await client.patch(
        f"/api/v1/tasks/{own.id}/status", json={"status": "in_progress"}, headers=caller.headers
    )
    others_move = await client.patch(
        f"/api/v1/tasks/{others.id}/status", json={"status": "in_progress"}, headers=caller.headers
    )

    assert own_move.status_code == 200
    assert others_move.status_code == 403
