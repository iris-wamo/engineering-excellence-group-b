"""Test database setup: an isolated PostgreSQL schema, an isolated MongoDB database,
and a per-test session that rolls back everything the test wrote.

Nothing here is autouse except the settings switch, so pure unit tests run without
PostgreSQL or MongoDB. Any test that asks for `db_session` (directly, or through
`client` or `factory`) gets both databases set up on first use.
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from asyncpg.exceptions import InvalidCatalogNameError
from pymongo import MongoClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base
from app.db.mongo import close_mongo_client, get_raw_task_imports_collection

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
    try:
        await _create_schema(engine)
    except InvalidCatalogNameError:
        await engine.dispose()
        # Stop the whole run: a fixture error would repeat for every database test.
        pytest.exit(
            _missing_test_database_message(_db_name), returncode=pytest.ExitCode.TESTS_FAILED
        )
    yield TEST_DATABASE_URL
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _missing_test_database_message(app_db_name: str) -> str:
    """Explain how to create the missing test database for a given app database name."""
    return (
        f'Test database "{app_db_name}_test" does not exist (the DATABASE_URL database name '
        'plus "_test").\n'
        "  - Docker: with the stack up, run `make docker-test-db`.\n"
        "  - Native PostgreSQL: create it as in README Step 3.\n"
        "  - Check that POSTGRES_DB matches the database name in DATABASE_URL; the container "
        "creates <POSTGRES_DB>_test."
    )


async def _create_schema(engine: AsyncEngine) -> None:
    """Rebuild every table in the test database and insert the default Workspace 1."""
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


@pytest.fixture(autouse=True)
async def close_app_mongo_client() -> AsyncGenerator[None, None]:
    """Close the app's shared Mongo client after every test.

    It is bound to the test's event loop, which closes when the test ends; a client left
    open there keeps its sockets until garbage collection. Opens no connection itself.
    """
    yield
    await close_mongo_client()


@asynccontextmanager
async def rolled_back_session(database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """A session inside one outer transaction that is rolled back on exit, even on error.

    Commits made by application code become savepoints inside that transaction, so code
    that commits still leaves nothing behind. Kept separate from the `db_session`
    fixture so tests/integration/test_db_session_isolation.py can check the rollback.
    """
    engine = create_async_engine(database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        testing_session_local = async_sessionmaker(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with testing_session_local() as session:
            yield session
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture()
async def db_session(
    test_database: str, test_mongo_database: str
) -> AsyncGenerator[AsyncSession, None]:
    """A database session whose writes are rolled back after the test.

    See `rolled_back_session`. The raw_task_imports collection is emptied before each
    test as well.
    """
    await get_raw_task_imports_collection().delete_many({})
    async with rolled_back_session(test_database) as session:
        yield session
