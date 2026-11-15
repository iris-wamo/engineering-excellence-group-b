"""Unit tests for per-request metrics and completion logs (ObservabilityMiddleware)."""

import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY
from taskflow_shared.errors.handlers import register_exception_handlers
from taskflow_shared.logging import JsonFormatter, bind_log_fields

from app.observability.metrics import UNMATCHED_ROUTE, metrics_endpoint
from app.observability.middleware import ObservabilityMiddleware

TASK_ROUTE = "/projects/{project_id}/tasks/{task_id}"


class JsonLines(logging.Handler):
    """Formats each record when it is emitted, while the request's log fields are bound."""

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(JsonFormatter().format(record)))


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware)
    register_exception_handlers(app)

    @app.get(TASK_ROUTE)
    async def get_task(project_id: int, task_id: int) -> dict[str, int]:
        bind_log_fields(user_id=9)
        return {"task_id": task_id}

    @app.get("/gone")
    async def gone() -> None:
        raise HTTPException(status_code=404)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    app.add_route("/metrics", metrics_endpoint)
    return app


@pytest.fixture()
def request_logs() -> Iterator[JsonLines]:
    handler = JsonLines()
    logger = logging.getLogger("app.requests")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


@pytest.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_build_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


def _requests(method: str, route: str, status: str) -> float:
    labels = {"method": method, "route": route, "status": status}
    return REGISTRY.get_sample_value("taskflow_http_requests_total", labels) or 0.0


def _durations(method: str, route: str) -> float:
    labels = {"method": method, "route": route}
    return REGISTRY.get_sample_value("taskflow_http_request_duration_seconds_count", labels) or 0.0


async def test_request_is_counted_and_timed_under_its_route_template(client: AsyncClient) -> None:
    before = _requests("GET", TASK_ROUTE, "200"), _durations("GET", TASK_ROUTE)

    response = await client.get("/projects/3/tasks/42")

    assert response.status_code == 200
    assert _requests("GET", TASK_ROUTE, "200") == before[0] + 1
    assert _durations("GET", TASK_ROUTE) == before[1] + 1


async def test_completion_log_has_operation_outcome_ids_and_duration(
    client: AsyncClient, request_logs: JsonLines
) -> None:
    await client.get("/projects/3/tasks/42", headers={"Authorization": "Bearer secret"})

    [entry] = request_logs.entries
    assert entry["operation"] == f"GET {TASK_ROUTE}"
    assert entry["outcome"] == "success"
    assert entry["status"] == 200
    assert entry["project_id"] == 3
    assert entry["task_id"] == 42
    assert entry["user_id"] == 9
    assert entry["duration_ms"] >= 0
    assert "secret" not in json.dumps(entry)


async def test_routes_in_nested_routers_keep_their_full_prefix(request_logs: JsonLines) -> None:
    inner = APIRouter(prefix="/projects")
    outer = APIRouter(prefix="/api/v9")

    @inner.get("/{project_id}")
    async def get_project(project_id: int) -> dict[str, int]:
        return {"project_id": project_id}

    @inner.get("")
    async def list_projects() -> list[int]:
        return []

    outer.include_router(inner)
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(outer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/v9/projects/5")
        await client.get("/api/v9/projects")

    assert [entry["operation"] for entry in request_logs.entries] == [
        "GET /api/v9/projects/{project_id}",
        "GET /api/v9/projects",
    ]


async def test_plain_routes_like_docs_are_labelled_by_their_path(client: AsyncClient) -> None:
    before = _requests("GET", "/docs", "200")

    await client.get("/docs")

    assert _requests("GET", "/docs", "200") == before + 1


async def test_unknown_paths_share_one_route_label(client: AsyncClient) -> None:
    before = _requests("GET", UNMATCHED_ROUTE, "404")

    await client.get("/no/such/path/123")
    await client.get("/another/unknown")

    assert _requests("GET", UNMATCHED_ROUTE, "404") == before + 2


async def test_handled_error_is_a_client_error_with_its_category(
    client: AsyncClient, request_logs: JsonLines
) -> None:
    response = await client.get("/gone")

    assert response.status_code == 404
    [entry] = request_logs.entries
    assert entry["outcome"] == "client_error"
    assert entry["error_category"] == "not_found"
    assert entry["level"] == "INFO"


async def test_unhandled_exception_is_counted_and_logged_as_a_server_error(
    client: AsyncClient, request_logs: JsonLines
) -> None:
    before = _requests("GET", "/boom", "500")

    response = await client.get("/boom")

    assert response.status_code == 500
    assert _requests("GET", "/boom", "500") == before + 1
    [entry] = request_logs.entries
    assert entry["outcome"] == "server_error"
    assert entry["error_category"] == "internal_server_error"
    assert entry["level"] == "ERROR"


async def test_unexpected_methods_share_one_method_label(client: AsyncClient) -> None:
    before = _requests("OTHER", UNMATCHED_ROUTE, "404")

    await client.request("PROPFIND", "/no/such/path")

    assert _requests("OTHER", UNMATCHED_ROUTE, "404") == before + 1


async def test_metrics_endpoint_serves_prometheus_text_and_is_not_counted(
    client: AsyncClient, request_logs: JsonLines
) -> None:
    await client.get("/projects/1/tasks/1")
    request_logs.entries.clear()

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "taskflow_http_requests_total" in response.text
    assert "taskflow_http_request_duration_seconds_bucket" in response.text
    assert 'route="/metrics"' not in response.text
    assert request_logs.entries == []
