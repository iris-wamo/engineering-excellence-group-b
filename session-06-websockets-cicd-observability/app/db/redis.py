"""Redis client helpers."""

import asyncio
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.core.config import settings
from app.db.loop_clients import LoopClients


def create_redis_client(**overrides: Any) -> Redis:
    """Create a new Redis client for settings.redis_url. Responses are decoded to str.

    Long-running consumers create their own client with `socket_timeout=None`, because
    a blocking XREADGROUP must be allowed to wait longer than a normal command.
    """
    options: dict[str, Any] = {
        "decode_responses": True,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
    }
    options.update(overrides)
    return Redis.from_url(str(settings.redis_url), **options)


def _create_request_path_client() -> Redis:
    # Used inside API requests, where a Redis outage must cost at most about a second.
    # redis-py's default policy retries 10 times with backoff, which kept a request
    # waiting about 24s against an unreachable server.
    return create_redis_client(
        socket_connect_timeout=1,
        socket_timeout=1,
        retry=Retry(NoBackoff(), retries=0),
    )


async def _close_redis(client: Redis) -> None:
    await client.aclose()


_redis_clients: LoopClients[Redis] = LoopClients(_create_request_path_client, _close_redis)


def get_redis_client() -> Redis:
    """Return the shared, fail-fast Redis client for the current event loop."""
    return _redis_clients.get(asyncio.get_running_loop())


async def close_redis_client() -> None:
    """Close the Redis client for the current event loop if open."""
    await _redis_clients.close(asyncio.get_running_loop())
