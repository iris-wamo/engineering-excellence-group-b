from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from taskflow_shared.logging import RequestIdMiddleware, configure_logging

from app.api.v1 import api_router
from app.core.exceptions import register_exception_handlers
from app.db.mongo import close_mongo_client, init_mongo_indexes
from app.db.redis import close_redis_client

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager."""
    await init_mongo_indexes()
    try:
        yield
    finally:
        try:
            await close_mongo_client()
        finally:
            await close_redis_client()


app = FastAPI(title="session-05-async-redis-celery", lifespan=lifespan)

app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)
app.include_router(api_router)
