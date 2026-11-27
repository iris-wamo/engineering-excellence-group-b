from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from taskflow_shared.logging import RequestIdMiddleware, configure_logging
from taskflow_shared.observability import ObservabilityMiddleware

from app.api.v1 import api_router
from app.api.version import router as version_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.mongo import close_mongo_client, init_mongo_indexes
from app.db.redis import close_redis_client
from app.observability.metrics import metrics_endpoint
from app.observability.tracing import instrument_api

configure_logging(level=settings.log_level, style=settings.log_format)


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


app = FastAPI(title="session-06-websockets-cicd-observability", lifespan=lifespan)

# Added first so it runs inside RequestIdMiddleware and its records carry the request id
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)
app.include_router(api_router)
# Operational, like /metrics: unversioned, so every release answers it the same way
app.include_router(version_router)
app.add_route("/metrics", metrics_endpoint, include_in_schema=False)
instrument_api(app)
