"""Prometheus metrics for HTTP requests.

Every label has a small, fixed set of values: HTTP methods, route templates (never raw
paths) and status codes. User, workspace, project and task IDs go in the logs instead,
because one series per ID would grow without bound.
"""

from prometheus_client import Counter, Histogram

# Label for requests that matched no route (404 scans, typos), so they share one series
UNMATCHED_ROUTE = "<unmatched>"

KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

HTTP_REQUESTS = Counter(
    "taskflow_http_requests",
    "HTTP requests handled by the API, by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "taskflow_http_request_duration_seconds",
    "Time the API took to handle a request, by method and route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def method_label(method: str) -> str:
    """Clients can send any method name; keep the label set fixed."""
    upper = method.upper()
    return upper if upper in KNOWN_METHODS else "OTHER"
