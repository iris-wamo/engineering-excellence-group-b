"""Test Redis setup: a dedicated logical database, emptied around every test that uses it.

Like the database fixtures, only the settings switch is autouse, so unit tests need no
Redis server. Tests that publish or consume events ask for `redis_client`.
"""

from collections.abc import AsyncGenerator, Generator

import pytest
from pydantic import RedisDsn
from redis.asyncio import Redis

from app.core.config import settings
from app.db.redis import close_redis_client, create_redis_client

# Logical database 15 of the same server, so tests never touch the app's events (db 0).
TEST_REDIS_DB = 15


def with_database(url: RedisDsn, database: int) -> RedisDsn:
    """The same Redis URL with only the database number replaced.

    Credentials, host, port, and query options (such as `?protocol=3`) are kept.
    """
    return RedisDsn.build(
        scheme=url.scheme,
        username=url.username,
        password=url.password,
        host=url.host or "localhost",
        port=url.port,
        path=str(database),
        query=url.query,
    )


@pytest.fixture(scope="session", autouse=True)
def use_test_redis_db() -> Generator[None, None]:
    """Point the app at the Redis test database. Only changes a setting, opens no connection."""
    original_redis_url = settings.redis_url
    settings.redis_url = with_database(original_redis_url, TEST_REDIS_DB)
    yield
    settings.redis_url = original_redis_url


@pytest.fixture()
async def redis_client() -> AsyncGenerator[Redis, None]:
    """A client on the empty Redis test database, flushed again after the test."""
    client = create_redis_client(socket_timeout=None)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()
    # The app's shared client is bound to this test's event loop, which is about to close.
    await close_redis_client()
