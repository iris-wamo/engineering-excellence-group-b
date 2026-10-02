"""FastAPI application entry point."""

from fastapi import FastAPI
from taskflow_shared.errors import register_exception_handlers
from taskflow_shared.logging import RequestIdMiddleware

from app.api.v1 import api_router

app = FastAPI(title="session-04-shared-backend-domain-rbac")

app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)
app.include_router(api_router)
