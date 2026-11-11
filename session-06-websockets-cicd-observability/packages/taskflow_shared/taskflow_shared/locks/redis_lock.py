"""Distributed lock on Redis: SET NX EX, token-checked release, and renewal while held."""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

RENEW_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
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


async def renew_redis_lock(
    redis_client: aioredis.Redis,
    lock_key: str,
    token: str,
    timeout_seconds: int,
) -> bool:
    """Atomically reset the lock's expiry, only if the token in Redis still matches."""
    result = await redis_client.eval(RENEW_LOCK_LUA, 1, lock_key, token, timeout_seconds)
    return bool(result == 1)


async def _keep_lock_alive(
    redis_client: aioredis.Redis, lock_key: str, token: str, timeout_seconds: int
) -> None:
    """Renew the lock every third of its TTL until cancelled, so a long run keeps it."""
    while True:
        await asyncio.sleep(timeout_seconds / 3)
        try:
            if not await renew_redis_lock(redis_client, lock_key, token, timeout_seconds):
                logger.warning("Lost Redis lock %s; another run may now overlap.", lock_key)
                return
        except Exception as exc:
            logger.warning("Error renewing Redis lock %s: %s", lock_key, exc)


@asynccontextmanager
async def distributed_lock(
    redis_client: aioredis.Redis,
    lock_key: str,
    timeout_seconds: int = 300,
) -> AsyncGenerator[str | None, None]:
    """Async context manager for acquiring and releasing a Redis distributed lock.

    Yields the lock token if acquired, or None if the lock is already held. While the
    block runs, the lock is renewed in the background, so it only expires (after
    timeout_seconds) if the holder dies without releasing it. The caller owns
    redis_client and closes it.
    """
    token: str | None = None
    keeper: asyncio.Task[None] | None = None
    try:
        token = await acquire_redis_lock(redis_client, lock_key, timeout_seconds=timeout_seconds)
        if token is not None:
            keeper = asyncio.create_task(
                _keep_lock_alive(redis_client, lock_key, token, timeout_seconds)
            )
        yield token
    finally:
        if keeper is not None:
            keeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keeper
        if token is not None:
            await release_redis_lock(redis_client, lock_key, token)
