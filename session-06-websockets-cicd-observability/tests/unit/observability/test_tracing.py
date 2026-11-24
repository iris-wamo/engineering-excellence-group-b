"""Unit tests for the tracing setup, the traced decorator and trace ids on log lines."""

import json
import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from taskflow_shared.logging import JsonFormatter
from taskflow_shared.observability import configure_tracing, traced


def _log_entry() -> dict[str, object]:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello", None, None)
    entry: dict[str, object] = json.loads(JsonFormatter().format(record))
    return entry


def test_tracing_is_not_configured_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    assert configure_tracing("taskflow-test") is False


async def test_traced_runs_the_call_in_a_named_span(spans: InMemorySpanExporter) -> None:
    @traced("Service.do_work")
    async def do_work(value: int) -> int:
        return value * 2

    assert await do_work(21) == 42
    [span] = spans.get_finished_spans()
    assert span.name == "Service.do_work"


async def test_traced_records_the_exception_and_reraises(spans: InMemorySpanExporter) -> None:
    @traced("Service.fail")
    async def fail() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await fail()
    [span] = spans.get_finished_spans()
    assert not span.status.is_ok
    assert span.events[0].name == "exception"


def test_log_lines_inside_a_span_carry_its_trace_and_span_id(spans: InMemorySpanExporter) -> None:
    with trace.get_tracer("test").start_as_current_span("work") as span:
        entry = _log_entry()

    context = span.get_span_context()
    assert entry["trace_id"] == format(context.trace_id, "032x")
    assert entry["span_id"] == format(context.span_id, "016x")


def test_log_lines_outside_a_span_have_no_trace_id() -> None:
    entry = _log_entry()

    assert "trace_id" not in entry
    assert "span_id" not in entry
