"""API tests for the /tasks/{id}/assign endpoint."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole
from app.models.project_user import ProjectUser
from app.schemas.project import ProjectCreate
from app.schemas.task import TaskCreate
from app.schemas.user import UserCreate
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.user_service import UserService


async def test_api_assign_task_success(client: AsyncClient, db_session: AsyncSession) -> None:
    creator = await UserService.create_user(
        db_session, UserCreate(name="Lead", email="lead@example.com")
    )
    assignee = await UserService.create_user(
        db_session, UserCreate(name="Engineer", email="engineer@example.com")
    )
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Payments"))
    db_session.add_all(
        [
            ProjectUser(project_id=project.id, user_id=creator.id, role=ProjectRole.owner),
            ProjectUser(project_id=project.id, user_id=assignee.id, role=ProjectRole.member),
        ]
    )
    await db_session.commit()

    task = await TaskService.create_task(
        db_session,
        TaskCreate(title="Stripe Integration", project_id=project.id),
    )

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={
            "assignee_id": assignee.id,
            "assigned_by_id": creator.id,
            "status": "in_progress",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task.id
    assert data["assignee_id"] == assignee.id
    assert data["status"] == "in_progress"


async def test_api_assign_task_failure_rollback(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    creator = await UserService.create_user(
        db_session, UserCreate(name="Lead2", email="lead2@example.com")
    )
    assignee = await UserService.create_user(
        db_session, UserCreate(name="Engineer2", email="engineer2@example.com")
    )
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Auth"))
    db_session.add_all(
        [
            ProjectUser(project_id=project.id, user_id=creator.id, role=ProjectRole.owner),
            ProjectUser(project_id=project.id, user_id=assignee.id, role=ProjectRole.member),
        ]
    )
    await db_session.commit()

    task = await TaskService.create_task(
        db_session,
        TaskCreate(title="OAuth2", project_id=project.id),
    )

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={
            "assignee_id": assignee.id,
            "assigned_by_id": creator.id,
            "simulate_failure": True,
        },
    )

    # Handled by handle_app_error with code SIMULATED_TRANSACTION_FAILURE
    assert response.status_code == 500
    err_body = response.json()
    assert err_body["error"]["code"] == "SIMULATED_TRANSACTION_FAILURE"

    # Verify task remains unchanged via GET
    get_res = await client.get(f"/api/v1/tasks/{task.id}")
    assert get_res.status_code == 200
    assert get_res.json()["assignee_id"] is None


async def test_api_assign_task_non_member_returns_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    creator = await UserService.create_user(
        db_session, UserCreate(name="Lead3", email="lead3@example.com")
    )
    outsider = await UserService.create_user(
        db_session, UserCreate(name="Outsider", email="outsider@example.com")
    )
    project = await ProjectService.create_project(db_session, ProjectCreate(name="Billing"))
    # Only creator is a member of Billing project
    db_session.add(ProjectUser(project_id=project.id, user_id=creator.id, role=ProjectRole.owner))
    await db_session.commit()

    task = await TaskService.create_task(
        db_session,
        TaskCreate(title="Invoice Generation", project_id=project.id),
    )

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={
            "assignee_id": outsider.id,
            "assigned_by_id": creator.id,
        },
    )

    assert response.status_code == 400
    err_body = response.json()
    assert err_body["error"]["code"] == "PROJECT_MEMBERSHIP_REQUIRED"
