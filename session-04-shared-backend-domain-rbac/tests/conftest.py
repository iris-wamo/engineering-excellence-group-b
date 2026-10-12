from collections.abc import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base
from app.db.mongo import get_raw_task_imports_collection
from app.db.session import get_db
from app.main import app

_base_url, _, _db_name = str(settings.database_url).rpartition("/")
TEST_DATABASE_URL = f"{_base_url}/{_db_name}_test"
TEST_MONGO_DB = f"{settings.mongo_db}_test"


@pytest.fixture(scope="session", autouse=True)
async def setup_database() -> AsyncGenerator[None, None]:
    """Creates the database schema once at the start of tests and drops it at the end."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def setup_mongo_database() -> Generator[None, None]:
    """Isolate tests into a separate Mongo test database and cleanup after session."""
    from typing import Any

    from pymongo import MongoClient

    original_mongo_db = settings.mongo_db
    settings.mongo_db = TEST_MONGO_DB

    # Setup index using sync client
    sync_client: MongoClient[dict[str, Any]] = MongoClient(
        str(settings.mongo_url), serverSelectionTimeoutMS=5000
    )
    sync_client[TEST_MONGO_DB]["raw_task_imports"].create_index(
        "idempotency_key", unique=True, sparse=True
    )

    yield

    sync_client.drop_database(TEST_MONGO_DB)
    sync_client.close()
    settings.mongo_db = original_mongo_db


@pytest.fixture(autouse=True)
async def clean_mongo_imports() -> None:
    """Ensure clean raw_task_imports collection before each test in test database."""
    col = get_raw_task_imports_collection()
    await col.delete_many({})


@pytest.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session that rolls back changes after each test."""
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
    """Fixture that provides an AsyncClient with overridden database dependency."""

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
