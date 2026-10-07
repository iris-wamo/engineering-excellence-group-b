from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import NamedTuple

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.enums import ProjectRole
from app.models.project import Project
from app.models.project_user import ProjectUser

_base_url, _, _db_name = str(settings.database_url).rpartition("/")
TEST_DATABASE_URL = f"{_base_url}/{_db_name}_test"


@pytest.fixture(scope="session", autouse=True)
async def setup_database() -> AsyncGenerator[None, None]:
    """Creates the database schema once at the start of tests and drops it at the end"""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session that rolls back changes after each test"""
    engine = create_async_engine(TEST_DATABASE_URL)
    connection = await engine.connect()
    transaction = await connection.begin()

    # join_transaction_mode="create_savepoint" captures commits inside code (rolling them back)
    testing_session_local = async_sessionmaker(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with testing_session_local() as session:
        yield session

    await transaction.rollback()
    await connection.close()
    await engine.dispose()


AUTH_USER = {"name": "Auth User", "email": "auth-user@example.com", "password": "sup3r-secret"}


@pytest.fixture()
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Fixture that provides an AsyncClient with overridden database dependency"""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Signs up AUTH_USER, logs in, and returns the Authorization header for that user"""
    await client.post("/api/v1/auth/signup", json=AUTH_USER)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": AUTH_USER["email"], "password": AUTH_USER["password"]},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class AuthedUser(NamedTuple):
    """A signed-up, logged-in user plus the header needed to act as them"""

    id: int
    headers: dict[str, str]


@pytest.fixture()
async def project(db_session: AsyncSession) -> Project:
    """A project for role memberships to hang off

    Inserted directly rather than through POST /api/v1/projects, because that endpoint
    is admin-only and granting the admin role already needs a project to exist.
    """
    project = Project(name="Fixture Project", slug="fixture-project")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture()
async def make_user(
    client: AsyncClient, db_session: AsyncSession, project: Project
) -> Callable[..., Awaitable[AuthedUser]]:
    """Factory that signs up a user and optionally gives them a role in a project"""

    async def _make(
        email: str, role: ProjectRole | None = None, *, project_id: int | None = None
    ) -> AuthedUser:
        password = "sup3r-secret"
        signup = await client.post(
            "/api/v1/auth/signup",
            json={"name": email.split("@")[0], "email": email, "password": password},
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

        login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        return AuthedUser(id=user_id, headers={"Authorization": f"Bearer {token}"})

    return _make


@pytest.fixture()
async def admin_headers(make_user: Callable[..., Awaitable[AuthedUser]]) -> dict[str, str]:
    """Authorization header for a user holding the admin role"""
    admin = await make_user("admin@example.com", ProjectRole.admin)
    return admin.headers
