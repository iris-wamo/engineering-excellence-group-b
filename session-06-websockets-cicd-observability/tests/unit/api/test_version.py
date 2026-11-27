"""Unit tests for GET /version, which deploy smoke tests use to check the serving build."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


async def test_version_reports_the_build_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_version", "v1.2.3")
    monkeypatch.setattr(settings, "git_sha", "abc123")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": "v1.2.3",
        "git_sha": "abc123",
        "environment": settings.environment.value,
    }
