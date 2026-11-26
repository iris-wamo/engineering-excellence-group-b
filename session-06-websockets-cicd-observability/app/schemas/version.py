"""Response schema for GET /version."""

from pydantic import BaseModel, ConfigDict


class VersionResponse(BaseModel):
    """Which build is serving: set at image build time, read by deploy smoke tests."""

    model_config = ConfigDict(frozen=True)

    version: str
    git_sha: str
    environment: str
