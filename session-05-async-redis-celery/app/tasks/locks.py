"""Distributed locking utilities backed by Redis for Celery tasks."""

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def acquire_redis_lock(
    redis_client: aioredis.Redis,
    lock_key: str,
    timeout_seconds: int = 300,
) -> str | None:
    """Attempt to acquire an exclusive lock using Redis SET NX EX.

    Returns the unique lock token if acquired, or None if the lock is already held.
    """
    token = str(uuid.uuid4())
    acquired = await redis_client.set(lock_key, token, nx=True, ex=timeout_seconds)
    if acquired:
        return token
    return None


async def release_redis_lock(
    redis_client: aioredis.Redis,
    lock_key: str,
    token: str,
) -> bool:
    """Atomically release the lock only if the token in Redis matches."""
    try:
        result = await redis_client.eval(RELEASE_LOCK_LUA, 1, lock_key, token)
        return bool(result == 1)
    except Exception as exc:
        logger.warning("Error releasing Redis lock %s: %s", lock_key, exc)
        return False


@asynccontextmanager
async def distributed_lock(
    lock_key: str,
    timeout_seconds: int = 300,
    redis_client: aioredis.Redis | None = None,
) -> AsyncGenerator[str | None, None]:
    """Async context manager for acquiring and releasing a Redis distributed lock.

    Yields the lock token if acquired, or None if the lock is already held.
    """
    client = redis_client
    owns_client = False
    if client is None:
        client = aioredis.from_url(str(settings.redis_url), decode_responses=True)
        owns_client = True

    token: str | None = None
    try:
        token = await acquire_redis_lock(client, lock_key, timeout_seconds=timeout_seconds)
        yield token
    finally:
        if token is not None:
            await release_redis_lock(client, lock_key, token)
        if owns_client and client is not None:
            await client.aclose()
