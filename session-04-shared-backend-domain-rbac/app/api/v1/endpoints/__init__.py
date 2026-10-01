from app.api.v1.endpoints.projects import router as projects_router
from app.api.v1.endpoints.tasks import router as tasks_router

__all__ = ["projects_router", "tasks_router"]
