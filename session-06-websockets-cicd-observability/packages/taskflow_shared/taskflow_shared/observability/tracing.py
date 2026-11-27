"""OpenTelemetry tracing setup and a decorator for spans around service calls."""

import functools
import os
from collections.abc import Callable, Coroutine
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_tracer = trace.get_tracer("taskflow")


def configure_tracing(service_name: str) -> bool:
    """Export spans over OTLP to OTEL_EXPORTER_OTLP_ENDPOINT, if set.

    Without the variable (tests, local runs without a collector) nothing is configured and
    every span is a no-op. Call once per process; in a forking server, after the fork,
    because the exporter's background thread does not survive it.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return True


def traced[**P, R](
    name: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """Run an async function inside a span called `name`, e.g. "TaskService.assign_task"."""

    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with _tracer.start_as_current_span(name):
                return await func(*args, **kwargs)

        return wrapper

    return decorator
