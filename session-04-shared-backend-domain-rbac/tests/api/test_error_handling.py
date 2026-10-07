"""Tests for standard ADR-001 error response envelopes and middleware behavior."""

from httpx import AsyncClient
from taskflow_shared.contracts.constants import HEADER_REQUEST_ID


async def test_unknown_route_returns_adr001_envelope(client: AsyncClient) -> None:
    """Verify 404 unknown routes use the standard ADR-001 error envelope."""
    response = await client.get("/api/v1/does-not-exist-at-all")

    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert data["error"]["message"] == "Not Found"
    assert isinstance(data["error"]["details"], list)
    assert HEADER_REQUEST_ID in response.headers


async def test_method_not_allowed_returns_adr001_envelope(client: AsyncClient) -> None:
    """Verify 405 returns ADR-001 error envelope and preserves Allow header."""
    response = await client.post("/api/v1/projects/1", json={})

    assert response.status_code == 405
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "Allow" in response.headers
    assert HEADER_REQUEST_ID in response.headers


async def test_app_level_validation_error_envelope(client: AsyncClient) -> None:
    """Verify app-level validation errors format into standard ADR-001 envelope with fields."""
    response = await client.post(
        "/api/v1/users",
        json={"email": "not-an-email", "full_name": ""},
    )

    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["message"] == "Request validation failed"
    assert len(data["error"]["details"]) > 0

    fields = {detail["field"] for detail in data["error"]["details"]}
    assert "email" in fields or "full_name" in fields
    assert HEADER_REQUEST_ID in response.headers
