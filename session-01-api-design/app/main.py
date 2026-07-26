from fastapi import FastAPI

from app.api.v1.endpoints.tasks import router as tasks_router
from app.core.exceptions import register_exception_handlers

app = FastAPI(title="session-01-api-design")

register_exception_handlers(app)
app.include_router(tasks_router)