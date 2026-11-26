"""Tracing for the API and the Celery worker (see docs/session-06/observability.md).

Spans go to the OTLP endpoint in OTEL_EXPORTER_OTLP_ENDPOINT (Tempo in Compose). The
instrumentation is always installed; without an endpoint its spans are no-ops.
"""

from fastapi import FastAPI
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from taskflow_shared.observability import configure_tracing

# Scrapes, deploy checks, the docs and the container healthcheck would only add noise
UNTRACED_URLS = "/metrics$,/version$,/docs,/openapi.json"


def instrument_api(app: FastAPI) -> None:
    configure_tracing("taskflow-api")
    FastAPIInstrumentor.instrument_app(app, excluded_urls=UNTRACED_URLS)
    # Engines are created lazily, after this runs (see app/db/session.py)
    SQLAlchemyInstrumentor().instrument()
    # Adds the trace context to queued jobs, so the worker's spans join the request's trace
    CeleryInstrumentor().instrument()


def instrument_worker() -> None:
    """Call in each pool process (worker_process_init), after the fork."""
    configure_tracing("taskflow-worker")
    SQLAlchemyInstrumentor().instrument()
    CeleryInstrumentor().instrument()
