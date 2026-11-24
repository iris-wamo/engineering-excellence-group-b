"""The real app's request records carry who made the request and in which workspace."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from taskflow_shared.logging import JsonFormatter

from tests.fixtures.auth import auth_headers_for
from tests.fixtures.factories import DEFAULT_WORKSPACE_ID, MISSING_ID, DataFactory


class JsonLines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(JsonFormatter().format(record)))


@pytest.fixture()
def request_logs() -> Iterator[JsonLines]:
    handler = JsonLines()
    logger = logging.getLogger("app.requests")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


async def test_authenticated_request_logs_user_workspace_and_request_id(
    client: AsyncClient, factory: DataFactory, request_logs: JsonLines
) -> None:
    user = await factory.user()
    headers = auth_headers_for(user.id, workspace_id=DEFAULT_WORKSPACE_ID)

    response = await client.get("/api/v1/projects", headers=headers)

    assert response.status_code == 200
    [entry] = request_logs.entries
    assert entry["operation"] == "GET /api/v1/projects"
    assert entry["user_id"] == user.id
    assert entry["workspace_id"] == DEFAULT_WORKSPACE_ID
    assert entry["request_id"] == response.headers["X-Request-ID"]
    assert headers["Authorization"].split()[1] not in json.dumps(entry)


async def test_domain_error_logs_its_code_and_the_project_id(
    client: AsyncClient, factory: DataFactory, request_logs: JsonLines
) -> None:
    user = await factory.user()
    headers = auth_headers_for(user.id, workspace_id=DEFAULT_WORKSPACE_ID)

    response = await client.get(f"/api/v1/projects/{MISSING_ID}", headers=headers)

    assert response.status_code == 404
    [entry] = request_logs.entries
    assert entry["operation"] == "GET /api/v1/projects/{project_id}"
    assert entry["outcome"] == "client_error"
    assert entry["error_category"] == response.json()["error"]["code"].lower()
    assert entry["project_id"] == MISSING_ID


async def test_anonymous_request_has_no_user_id(
    client: AsyncClient, request_logs: JsonLines
) -> None:
    """An invalid token is treated as anonymous, which still falls back to Workspace 1."""
    await client.get("/api/v1/projects", headers={"Authorization": "Bearer not-a-jwt"})

    [entry] = request_logs.entries
    assert "user_id" not in entry
    assert entry["workspace_id"] == DEFAULT_WORKSPACE_ID
