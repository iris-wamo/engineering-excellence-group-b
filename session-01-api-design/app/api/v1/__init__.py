from fastapi import APIRouter

from app.api.v1.endpoints import projects_router, tasks_router
from app.api.v1.users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(projects_router)
api_router.include_router(users_router)
api_router.include_router(tasks_router)

__all__ = ["api_router"]
