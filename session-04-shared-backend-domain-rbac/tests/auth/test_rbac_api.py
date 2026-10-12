"""One allowed and one denied test per row of docs/rbac-authorization-matrix.md."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole, TaskStatus
from app.models.project import Project
from app.models.task import Task
from tests.conftest import AuthedUser

MakeUser = Callable[..., Awaitable[AuthedUser]]


async def _add_task(
    db_session: AsyncSession, project: Project, assignee_id: int | None = None
) -> Task:
    task = Task(title="Task", project_id=project.id, assignee_id=assignee_id)
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


async def test_admin_can_create_project(client: AsyncClient, make_user: MakeUser) -> None:
    admin = await make_user("admin@example.com", ProjectRole.admin)

    response = await client.post(
        "/api/v1/projects", json={"name": "New Project"}, headers=admin.headers
    )

    assert response.status_code == 201


async def test_manager_cannot_create_project(client: AsyncClient, make_user: MakeUser) -> None:
    manager = await make_user("manager@example.com", ProjectRole.manager)

    response = await client.post(
        "/api/v1/projects", json={"name": "New Project"}, headers=manager.headers
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_member_cannot_create_project(client: AsyncClient, make_user: MakeUser) -> None:
    member = await make_user("member@example.com", ProjectRole.member)

    response = await client.post(
        "/api/v1/projects", json={"name": "New Project"}, headers=member.headers
    )

    assert response.status_code == 403


async def test_user_with_no_role_cannot_create_project(
    client: AsyncClient, make_user: MakeUser
) -> None:
    nobody = await make_user("nobody@example.com")

    response = await client.post(
        "/api/v1/projects", json={"name": "New Project"}, headers=nobody.headers
    )

    assert response.status_code == 403


async def test_admin_can_manage_users(client: AsyncClient, make_user: MakeUser) -> None:
    admin = await make_user("admin@example.com", ProjectRole.admin)

    response = await client.post(
        "/api/v1/users",
        json={"name": "Created", "email": "created@example.com"},
        headers=admin.headers,
    )

    assert response.status_code == 201


async def test_manager_cannot_manage_users(client: AsyncClient, make_user: MakeUser) -> None:
    manager = await make_user("manager@example.com", ProjectRole.manager)

    response = await client.post(
        "/api/v1/users",
        json={"name": "Created", "email": "created@example.com"},
        headers=manager.headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_member_cannot_manage_users(client: AsyncClient, make_user: MakeUser) -> None:
    member = await make_user("member@example.com", ProjectRole.member)

    response = await client.post(
        "/api/v1/users",
        json={"name": "Created", "email": "created@example.com"},
        headers=member.headers,
    )

    assert response.status_code == 403


async def test_manager_can_assign_task(
    client: AsyncClient, db_session: AsyncSession, project: Project, make_user: MakeUser
) -> None:
    manager = await make_user("manager@example.com", ProjectRole.manager)
    member = await make_user("member@example.com", ProjectRole.member)
    task = await _add_task(db_session, project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": member.id, "assigned_by_id": manager.id},
        headers=manager.headers,
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] == member.id


async def test_admin_can_assign_task(
    client: AsyncClient, db_session: AsyncSession, project: Project, make_user: MakeUser
) -> None:
    admin = await make_user("admin@example.com", ProjectRole.admin)
    member = await make_user("member@example.com", ProjectRole.member)
    task = await _add_task(db_session, project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": member.id, "assigned_by_id": admin.id},
        headers=admin.headers,
    )

    assert response.status_code == 200


async def test_member_cannot_assign_task(
    client: AsyncClient, db_session: AsyncSession, project: Project, make_user: MakeUser
) -> None:
    member = await make_user("member@example.com", ProjectRole.member)
    task = await _add_task(db_session, project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": member.id, "assigned_by_id": member.id},
        headers=member.headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_manager_of_another_project_cannot_assign_task(
    client: AsyncClient, db_session: AsyncSession, project: Project, make_user: MakeUser
) -> None:
    """Roles are per project, so a manager elsewhere has no say in this project."""
    other_project = Project(name="Other", slug="other")
    db_session.add(other_project)
    await db_session.commit()
    await db_session.refresh(other_project)

    outsider = await make_user(
        "outsider@example.com", ProjectRole.manager, project_id=other_project.id
    )
    task = await _add_task(db_session, project)

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": outsider.id, "assigned_by_id": outsider.id},
        headers=outsider.headers,
    )

    assert response.status_code == 403


async def test_member_can_update_status_of_own_task(
    client: AsyncClient, db_session: AsyncSession, project: Project, make_user: MakeUser
) -> None:
    member = await make_user("member@example.com", ProjectRole.member)
    task = await _add_task(db_session, project, assignee_id=member.id)

    response = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": TaskStatus.in_progress.value},
        headers=member.headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == TaskStatus.in_progress.value


async def test_member_cannot_update_status_of_someone_elses_task(
    client: AsyncClient, db_session: AsyncSession, project: Project, make_user: MakeUser
) -> None:
    member = await make_user("member@example.com", ProjectRole.member)
    other = await make_user("other@example.com", ProjectRole.member)
    task = await _add_task(db_session, project, assignee_id=other.id)

    response = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": TaskStatus.done.value},
        headers=member.headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_admin_cannot_update_status_of_someone_elses_task(
    client: AsyncClient, db_session: AsyncSession, project: Project, make_user: MakeUser
) -> None:
    """Status is an ownership check, so even an admin must be the assignee."""
    admin = await make_user("admin@example.com", ProjectRole.admin)
    member = await make_user("member@example.com", ProjectRole.member)
    task = await _add_task(db_session, project, assignee_id=member.id)

    response = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": TaskStatus.done.value},
        headers=admin.headers,
    )

    assert response.status_code == 403


async def test_unauthenticated_project_create_returns_401(client: AsyncClient) -> None:
    response = await client.post("/api/v1/projects", json={"name": "New Project"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_unauthenticated_user_create_returns_401(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users", json={"name": "Created", "email": "created@example.com"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_unauthenticated_task_assign_returns_401(
    client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    task = await _add_task(db_session, project)

    response = await client.post(f"/api/v1/tasks/{task.id}/assign", json={"assignee_id": None})

    assert response.status_code == 401


async def test_unauthenticated_status_update_returns_401(
    client: AsyncClient, db_session: AsyncSession, project: Project
) -> None:
    task = await _add_task(db_session, project)

    response = await client.patch(
        f"/api/v1/tasks/{task.id}/status", json={"status": TaskStatus.done.value}
    )

    assert response.status_code == 401
