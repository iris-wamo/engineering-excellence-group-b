"""Cache-aside storage for a workspace's task summary metrics.

Only the aggregated database metrics are cached, never the simulated external call: that
call is a per-request demo (`external_delay`, `external_timeout`) and must stay live.

Keys are `taskflow:v1:ws:<workspace_id>:task_summary:v<version>`, where `<version>` is a
per-workspace counter stored at `taskflow:v1:ws:<workspace_id>:task_summary:version`. A
reader notes the version before it queries the database and stores its result under that
version, so a result computed before a change can never be stored over newer data: the
change moves the workspace to a new version and the old entry is never read again.

Redis is an optimisation here. Every function fails open: when Redis is unreachable the
caller gets a miss and the request is served from the database.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from redis.exceptions import RedisError

from app.core.config import settings
from app.db.redis import get_redis_client

logger = logging.getLogger(__name__)

_KEY_PREFIX = "taskflow:v1"


def version_key(workspace_id: int) -> str:
    return f"{_KEY_PREFIX}:ws:{workspace_id}:task_summary:version"


def summary_key(workspace_id: int, version: int) -> str:
    return f"{_KEY_PREFIX}:ws:{workspace_id}:task_summary:v{version}"


@dataclass(frozen=True)
class SummaryLookup:
    """Result of a cache read."""

    metrics: dict[str, Any] | None
    """The cached metrics, or None on a miss."""
    version: int | None
    """Version the lookup read. Pass it to `store_summary`. None if Redis was unavailable."""


async def lookup_summary(workspace_id: int) -> SummaryLookup:
    """Read the workspace's cached metrics. Never raises."""
    try:
        redis = get_redis_client()
        raw_version = await redis.get(version_key(workspace_id))
        version = int(raw_version) if raw_version is not None else 0
        raw = await redis.get(summary_key(workspace_id, version))
    except (RedisError, OSError, ValueError):
        logger.warning(
            "Task summary cache unavailable for workspace_id=%s, using the database",
            workspace_id,
            exc_info=True,
        )
        return SummaryLookup(metrics=None, version=None)

    if raw is None:
        logger.info("Task summary cache MISS workspace_id=%s version=%d", workspace_id, version)
        return SummaryLookup(metrics=None, version=version)

    try:
        metrics = json.loads(raw)
    except ValueError:
        logger.warning(
            "Task summary cache entry is not valid JSON, treating as a miss workspace_id=%s",
            workspace_id,
        )
        return SummaryLookup(metrics=None, version=version)

    logger.info("Task summary cache HIT workspace_id=%s version=%d", workspace_id, version)
    return SummaryLookup(metrics=metrics, version=version)


async def store_summary(workspace_id: int, version: int | None, metrics: dict[str, Any]) -> None:
    """Store metrics under the version the lookup read, with a TTL. Never raises.

    The TTL bounds how long a value can outlive a missed invalidation, and it also covers
    `overdue_count`, which changes at midnight without any task being written.
    """
    if version is None:
        return
    try:
        await get_redis_client().set(
            summary_key(workspace_id, version),
            json.dumps(metrics),
            ex=settings.task_summary_cache_ttl_seconds,
        )
    except (RedisError, OSError):
        logger.warning(
            "Could not store task summary in cache workspace_id=%s", workspace_id, exc_info=True
        )


async def invalidate_summary(workspace_id: int) -> None:
    """Move the workspace to a new cache version, so its cached summary is never read again.

    Call after the database commit of any change that alters the summary. The old entry is
    not deleted: it can no longer be reached and expires on its own TTL. Never raises: if
    Redis is unreachable the change stays committed and stale data is bounded by the TTL.
    """
    try:
        new_version = await get_redis_client().incr(version_key(workspace_id))
    except (RedisError, OSError):
        logger.warning(
            "Could not invalidate task summary cache workspace_id=%s, stale data possible for up "
            "to %ds",
            workspace_id,
            settings.task_summary_cache_ttl_seconds,
            exc_info=True,
        )
        return
    logger.info(
        "Task summary cache INVALIDATED workspace_id=%s version=%d", workspace_id, new_version
    )
