"""MongoDB database client and collection helpers."""

from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection

from app.core.config import settings

_mongo_client: MongoClient[dict[str, Any]] | None = None


def get_mongo_client() -> MongoClient[dict[str, Any]]:
    """Return a singleton MongoClient instance."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(
            str(settings.mongo_url),
            serverSelectionTimeoutMS=5000,
        )
    return _mongo_client


def get_raw_task_imports_collection() -> Collection[dict[str, Any]]:
    """Return the raw_task_imports MongoDB collection."""
    client = get_mongo_client()
    return client[settings.mongo_db]["raw_task_imports"]


def close_mongo_client() -> None:
    """Close the MongoClient connection if open."""
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None
