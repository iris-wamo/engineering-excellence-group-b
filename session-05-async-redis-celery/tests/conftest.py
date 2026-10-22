"""Suite-wide fixtures.

Database fixtures live in tests/fixtures/database.py and are registered as a plugin
below. Data factories are in tests/fixtures/factories.py and token helpers in
tests/fixtures/auth.py. Test modules import helpers and types from tests.fixtures,
never from this file.
"""

from collections.abc import AsyncGenerator
from pathlib import Path

# On macOS, the default per-process file descriptor limit in Terminal is 256.
# Running large integration suites exhausts this limit, causing OSError 24 (Too many open files)
# and getaddrinfo failures. Automatically raise the soft limit up to the hard limit or 4096.
try:
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < 4096:
        target = min(4096, hard) if hard > 0 else 4096
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
except (ImportError, ValueError, OSError):
    pass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.enums import ProjectRole
from app.models.project import Project
from app.models.project_user import ProjectUser
from tests.fixtures.auth import (
    AUTH_USER,
    DEFAULT_PASSWORD,
    AuthedUser,
    MakeUser,
    auth_headers_for,
)
from tests.fixtures.factories import DEFAULT_WORKSPACE_ID, DataFactory

pytest_plugins = ["tests.fixtures.database"]

# Every test is marked after the top-level folder it lives in (tests/unit, tests/integration,
# tests/auth), so `pytest -m unit` runs only the tests that need no database. Tests outside
# tests/ (the taskflow_shared package) are pure, so they count as unit. Anything else is
# treated as integration, the safe assumption. See docs/testing-strategy.md.
_FOLDER_MARKERS = {"unit", "integration", "auth"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    tests_root = Path(__file__).parent
    for item in items:
        path = Path(str(item.path))
        if tests_root not in path.parents:
            item.add_marker("unit")
            continue
        folder = path.relative_to(tests_root).parts[0]
        item.add_marker(folder if folder in _FOLDER_MARKERS else "integration")


@pytest.fixture()
async def factory(db_session: AsyncSession) -> DataFactory:
    """Factory for users, workspaces, projects, roles, and tasks in the test session."""
    return DataFactory(db_session)


@pytest.fixture()
async def viewer_headers(factory: DataFactory) -> dict[str, str]:
    """Headers for a Workspace 1 member with no project role.

    Use it for reads and validation checks so a test does not depend on anonymous
    requests falling back to Workspace 1, a known limitation that is due to be switched
    off (see docs/multi-tenancy-architecture.md, Known Limitations).
    """
    user = await factory.user()
    return auth_headers_for(user.id, workspace_id=DEFAULT_WORKSPACE_ID)


@pytest.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Fixture that provides an AsyncClient with overridden database dependency."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Signs up AUTH_USER, logs in, and returns the Authorization header for that user"""
    await client.post("/api/v1/auth/signup", json=AUTH_USER)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": AUTH_USER["email"], "password": AUTH_USER["password"]},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
async def project(factory: DataFactory) -> Project:
    """A project for role memberships to hang off

    Inserted directly rather than through POST /api/v1/projects, because that endpoint
    is admin-only and granting the admin role already needs a project to exist.
    """
    return await factory.project(name="Fixture Project", slug="fixture-project")


@pytest.fixture()
async def make_user(client: AsyncClient, db_session: AsyncSession, project: Project) -> MakeUser:
    """Factory that signs up a user through the real API and optionally gives them a role

    Prefer `factory.member(...)` in new tests. It is faster because it skips password
    hashing and the signup/login round trip. Use this one when going through
    signup and login is part of what the test covers.
    """

    async def _make(
        email: str, role: ProjectRole | None = None, *, project_id: int | None = None
    ) -> AuthedUser:
        signup = await client.post(
            "/api/v1/auth/signup",
            json={"name": email.split("@")[0], "email": email, "password": DEFAULT_PASSWORD},
        )
        user_id = signup.json()["id"]

        if role is not None:
            db_session.add(
                ProjectUser(
                    project_id=project_id if project_id is not None else project.id,
                    user_id=user_id,
                    role=role,
                )
            )
            await db_session.commit()

        login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
        )
        token = login.json()["access_token"]
        return AuthedUser(id=user_id, headers={"Authorization": f"Bearer {token}"})

    return _make


@pytest.fixture()
async def admin_headers(make_user: MakeUser) -> dict[str, str]:
    """Authorization header for a user holding the admin role"""
    admin = await make_user("admin@example.com", ProjectRole.admin)
    return admin.headers
