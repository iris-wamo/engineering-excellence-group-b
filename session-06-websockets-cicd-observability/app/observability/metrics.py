"""Prometheus metrics for Celery task runs, and the API's /metrics endpoint.

HTTP request metrics live in taskflow_shared.observability. Labels have a small, fixed set of
values (task names, outcomes); IDs go in the logs.
"""

import secrets

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.exceptions import NotAuthenticatedError

CELERY_TASKS = Counter(
    "taskflow_celery_tasks",
    "Celery task runs, by task name and outcome (succeeded, failed, retried).",
    ["task", "outcome"],
)
CELERY_TASK_DURATION = Histogram(
    "taskflow_celery_task_duration_seconds",
    "Time a Celery task run took, by task name.",
    ["task"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)


async def metrics_endpoint(request: Request) -> Response:
    """Serve the API process's metrics in the Prometheus text format.

    With METRICS_TOKEN set, the scraper must send it as a bearer token.
    """
    if settings.metrics_token is not None:
        sent = request.headers.get("authorization", "").encode()
        if not secrets.compare_digest(sent, f"Bearer {settings.metrics_token}".encode()):
            raise NotAuthenticatedError()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
