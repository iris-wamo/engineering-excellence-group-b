"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.exceptions import register_exception_handlers

app = FastAPI(title="session-04-shared-backend-domain-rbac")

register_exception_handlers(app)
app.include_router(api_router)
