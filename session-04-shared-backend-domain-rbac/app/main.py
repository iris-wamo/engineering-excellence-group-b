from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from taskflow_shared.logging import RequestIdMiddleware, configure_logging

from app.api.v1 import api_router
from app.core.exceptions import register_exception_handlers
from app.db.mongo import close_mongo_client

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager."""
    yield
    close_mongo_client()


app = FastAPI(title="session-04-shared-backend-domain-rbac", lifespan=lifespan)

app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)
app.include_router(api_router)
