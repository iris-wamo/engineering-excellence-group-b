"""One request through the real app produces a trace with route, service and database spans."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from redis.asyncio import Redis
from taskflow_shared.logging import JsonFormatter

from app.models.enums import ProjectRole
from tests.fixtures.factories import DataFactory


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


async def test_assignment_trace_has_route_service_and_database_spans(
    client: AsyncClient,
    factory: DataFactory,
    redis_client: Redis,
    spans: InMemorySpanExporter,
    request_logs: JsonLines,
) -> None:
    project = await factory.project()
    manager = await factory.member(project, ProjectRole.manager)
    assignee = await factory.member(project)
    task = await factory.task(project)
    spans.clear()

    response = await client.post(
        f"/api/v1/tasks/{task.id}/assign",
        json={"assignee_id": assignee.id},
        headers=manager.headers,
    )

    assert response.status_code == 200
    finished = spans.get_finished_spans()
    [server] = [s for s in finished if s.attributes and "http.route" in s.attributes]
    assert server.attributes is not None
    assert server.attributes["http.route"] == "/api/v1/tasks/{task_id}/assign"
    trace_id = server.context.trace_id
    in_trace = [s for s in finished if s.context.trace_id == trace_id]

    assert any(s.name == "TaskService.assign_task" for s in in_trace)
    assert any(s.attributes and "db.statement" in s.attributes for s in in_trace)
    # The request's log record can be found from the trace and the other way round
    [entry] = request_logs.entries
    assert entry["trace_id"] == format(trace_id, "032x")


async def test_metrics_scrapes_are_not_traced(
    client: AsyncClient, spans: InMemorySpanExporter
) -> None:
    await client.get("/metrics")

    assert spans.get_finished_spans() == ()
