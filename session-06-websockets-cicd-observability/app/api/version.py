"""GET /version: the build identity of the running API (see docs/session-06/ci-cd.md)."""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.version import VersionResponse

router = APIRouter(tags=["version"])


@router.get("/version", response_model=VersionResponse)
async def read_version() -> VersionResponse:
    """Return the app version and git commit this image was built from."""
    return VersionResponse(
        version=settings.app_version,
        git_sha=settings.git_sha,
        environment=settings.environment.value,
    )
