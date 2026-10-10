"""MongoDB database client and collection helpers."""

import asyncio
import logging
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from app.core.config import settings

logger = logging.getLogger(__name__)

_mongo_clients: dict[asyncio.AbstractEventLoop, AsyncMongoClient[dict[str, Any]]] = {}
_default_client: AsyncMongoClient[dict[str, Any]] | None = None


def get_mongo_client() -> AsyncMongoClient[dict[str, Any]]:
    """Return an AsyncMongoClient bound to the current running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        client = _mongo_clients.get(loop)
        if client is None:
            client = AsyncMongoClient(
                str(settings.mongo_url),
                serverSelectionTimeoutMS=5000,
                tz_aware=True,
            )
            _mongo_clients[loop] = client
        return client

    global _default_client
    if _default_client is None:
        _default_client = AsyncMongoClient(
            str(settings.mongo_url),
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
        )
    return _default_client


def get_raw_task_imports_collection(
    database_name: str | None = None,
) -> AsyncCollection[dict[str, Any]]:
    """Return the raw_task_imports MongoDB collection."""
    client = get_mongo_client()
    db_name = database_name or settings.mongo_db
    return client[db_name]["raw_task_imports"]


async def init_mongo_indexes(database_name: str | None = None) -> None:
    """Ensure required indexes exist on MongoDB collections."""
    try:
        col = get_raw_task_imports_collection(database_name)
        await col.create_index("idempotency_key", unique=True, sparse=True)
    except Exception as exc:
        logger.warning("Could not initialize MongoDB indexes: %s", exc)


async def close_mongo_client() -> None:
    """Close the AsyncMongoClient connection for the current loop if open."""
    try:
        loop = asyncio.get_running_loop()
        client = _mongo_clients.pop(loop, None)
        if client is not None:
            await client.close()
    except RuntimeError:
        pass

    global _default_client
    if _default_client is not None:
        await _default_client.close()
        _default_client = None
