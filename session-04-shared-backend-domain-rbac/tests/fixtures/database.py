"""Test database setup: an isolated PostgreSQL schema, an isolated MongoDB database,
and a per-test session that rolls back everything the test wrote.

Nothing here is autouse except the settings switch, so pure unit tests run without
PostgreSQL or MongoDB. Any test that asks for `db_session` (directly, or through
`client` or `factory`) gets both databases set up on first use.
"""

from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from pymongo import MongoClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.db.mongo import get_raw_task_imports_collection

_base_url, _, _db_name = str(settings.database_url).rpartition("/")
TEST_DATABASE_URL = f"{_base_url}/{_db_name}_test"
TEST_MONGO_DB = f"{settings.mongo_db}_test"


@pytest.fixture(scope="session", autouse=True)
def use_test_mongo_db() -> Generator[None, None]:
    """Point the app at the Mongo test database so no test can touch real data.

    Only changes a setting and opens no connection, so it is safe for unit tests.
    """
    original_mongo_db = settings.mongo_db
    settings.mongo_db = TEST_MONGO_DB
    yield
    settings.mongo_db = original_mongo_db


@pytest.fixture(scope="session")
async def test_database() -> AsyncGenerator[str, None]:
    """Create the PostgreSQL schema once per session (with Workspace 1) and drop it at the end."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO workspace (id, name, slug, description, created_at, updated_at) "
                "VALUES (1, 'Default Workspace', 'default-workspace', "
                "'System default workspace', NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING;"
            )
        )
        await connection.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('workspace', 'id'), "
                "COALESCE((SELECT MAX(id) FROM workspace), 1));"
            )
        )
    yield TEST_DATABASE_URL
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="session")
def test_mongo_database() -> Generator[str, None]:
    """Create the Mongo test database indexes once per session and drop the database at the end."""
    sync_client: MongoClient[dict[str, Any]] = MongoClient(
        str(settings.mongo_url), serverSelectionTimeoutMS=5000
    )
    sync_client[TEST_MONGO_DB]["raw_task_imports"].create_index(
        [("workspace_id", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
        name="uq_workspace_idempotency_key",
    )
    yield TEST_MONGO_DB
    sync_client.drop_database(TEST_MONGO_DB)
    sync_client.close()


@pytest.fixture()
async def db_session(
    test_database: str, test_mongo_database: str
) -> AsyncGenerator[AsyncSession, None]:
    """A database session whose writes are rolled back after the test.

    Commits made by application code become savepoints inside one outer transaction,
    so tests can call services that commit and still leave nothing behind.
    The raw_task_imports collection is emptied before each test as well.
    """
    await get_raw_task_imports_collection().delete_many({})

    engine = create_async_engine(test_database)
    connection = await engine.connect()
    transaction = await connection.begin()

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
