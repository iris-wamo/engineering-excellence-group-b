# Observability

How TaskFlow records what happened (logs) and how much of it happened (metrics). Tracing and the
Grafana dashboard come in #126, health checks and the incident simulation in #127.

## Overview

| Signal | Where it is produced | Where to read it |
|---|---|---|
| Request log record | `ObservabilityMiddleware` (`app/observability/middleware.py`), one per HTTP request | API container stdout |
| Task log record | Celery signal handlers (`app/core/celery_app.py` → `app/observability/celery.py`), one per task run | Worker container stdout |
| API metrics | Same middleware, `prometheus_client` default registry | `GET /metrics` on the API (port 8000) |
| Worker metrics | Same signal handlers, multiprocess mode | `GET /metrics` on the worker, `127.0.0.1:9808` |

## Structured logs

Every line is one JSON object (`LOG_FORMAT=json`, the default). `LOG_FORMAT=text` keeps the
session-05 text format for local reading; both carry the request id.

### Fields

| Field | Request record | Task record | Set by |
|---|---|---|---|
| `timestamp`, `level`, `logger`, `message` | ✓ | ✓ | `JsonFormatter` |
| `request_id` | ✓ | ✓ (the API request that queued the job; `null` for Beat jobs) | `RequestIdMiddleware`, Celery headers |
| `operation` | `GET /api/v1/projects/{project_id}` | task name | middleware / signal handler |
| `outcome` | `success`, `client_error`, `server_error` | `succeeded`, `failed`, `retried` | middleware / signal handler |
| `status` | HTTP status | | middleware |
| `duration_ms` | ✓ | ✓ | middleware / signal handler |
| `error_category` | error envelope code, lower case (`not_found`, `validation_error`, `internal_server_error`) | exception class (`ConnectionError`) | exception handlers / `task_failure`, `task_retry` |
| `user_id` | when authenticated | | `get_current_user`, `get_optional_current_user` |
| `workspace_id` | when resolved | | `get_current_workspace_id` |
| `project_id`, `task_id` | from the path, when present | | middleware |
| `task_name`, `celery_task_id` | | ✓ (named so it never clashes with the TaskFlow `task_id`) | signal handler |
| `retries` | | ✓ | signal handler |
| `exc_type`, `exc_info` | on `logger.exception` | on `logger.exception` | `JsonFormatter` |

Any other log call in the app picks up the same bound fields, so a warning logged deep in a
service during a request also has `user_id`, `workspace_id` and `request_id`.

### How fields get onto the record

`start_log_context()` puts an empty dict in a context variable when a request or task run
starts. `bind_log_fields(...)` updates that dict **in place**. In-place matters: FastAPI runs
dependencies and handlers in child tasks and threads, which copy context variables. A new value set
there would not be visible to the middleware that writes the final record, but a change to the
shared dict is. The formatter merges the dict into every record at the moment it is written, so
handlers must format synchronously (a `StreamHandler` does; a `QueueHandler` would lose the fields).

### What is never logged

- Values of keys containing `password`, `token`, `secret`, `authorization`, `api_key`, `cookie`
  or `credential` (case-insensitive, `-` treated as `_`), at any depth, are replaced with `[REDACTED]`.
- `Bearer ...` values and anything shaped like a JWT are masked inside the message text too.
- Request and response bodies are not logged at all. Redacting known keys is a safety net, not a
  reason to start logging payloads.

Text redaction is best effort: a secret with no recognisable key or shape (a password pasted into
a task title) would still be logged. The protection that holds is not logging bodies.

## Metrics

| Metric | Type | Labels |
|---|---|---|
| `taskflow_http_requests_total` | counter | `method`, `route`, `status` |
| `taskflow_http_request_duration_seconds` | histogram | `method`, `route` |
| `taskflow_celery_tasks_total` | counter | `task`, `outcome` |
| `taskflow_celery_task_duration_seconds` | histogram | `task` |

Error rate is `taskflow_http_requests_total{status=~"5.."}` over all requests; client errors are
`status=~"4.."`. A separate error counter would duplicate what the status label already says.

The WebSocket connection gauge is defined by #120 with `prometheus_client`; it appears on the
same `/metrics` endpoint without changes here.

### Labels and cardinality

Each label value creates a separate time series, so every label has a small, fixed set of values:

- `route` is the **route template** (`/api/v1/tasks/{task_id}`), never the raw path. Requests that
  match no route share `<unmatched>`, so a scanner trying random URLs adds one series, not thousands.
- `method` is one of the standard methods; anything else (`PROPFIND`) is `OTHER`.
- `status` is the status code; the app returns a few dozen at most.
- `task` is the registered Celery task name; `outcome` has three values.
- User, workspace, project and task IDs are **not** labels. They grow with the data, and Prometheus
  would keep a series per ID forever. They are in the logs, where looking up one ID is cheap.

Histogram buckets cover 5 ms to 10 s for requests and 10 ms to 60 s for tasks, so p95 can be
estimated in the range the app actually runs in.

#### Getting the route template

FastAPI 0.139 keeps included routers nested: the matched route only knows its path inside its own
router (`/projects/{project_id}`), not the `/api/v1` prefix. The middleware rebuilds the prefix by
filling the route's template with the path params and removing that from the end of the request
path. This works because router prefixes here are static. FastAPI also does not record plain routes
like `/docs` in the scope, so those are found by their endpoint. FastAPI does keep the full path
under a private scope key; it was not used because private keys can change in any release.

### Why the worker serves its own metrics

The Celery worker runs tasks in forked child processes, each with its own memory, so each child
would count only its own runs, and no single process could report the total. The worker uses
`prometheus_client` multiprocess mode instead:

- `PROMETHEUS_MULTIPROC_DIR` is set for the worker (Compose: `/tmp/prometheus-worker`;
  `make celery-worker`: `/tmp/taskflow-worker-metrics`). Children write their values to files there.
- On `worker_init` the main process clears files left by an earlier run, then serves the sum of all
  files on `WORKER_METRICS_PORT` (default 9808).
- If the variable is not set, the worker logs a warning and serves nothing, rather than serving
  numbers that silently miss the children's work.

The API runs as one uvicorn process, so it uses the default registry. Running uvicorn with several
workers would need the same multiprocess setup there.

**Rejected alternative: Flower's `/metrics`.** Flower already exports task events as Prometheus
metrics, so it would have needed no code. It was not used because its numbers come from the Celery
events Flower asks workers to send while it is connected: if Flower is down or restarts, runs in
that window are never counted. The worker's own counters do not depend on another process being up.
Both can run side by side.

## Trying it

```bash
make docker-up
curl -s localhost:8000/api/v1/projects > /dev/null
curl -s localhost:8000/api/v1/projects/999999 > /dev/null
curl -s localhost:8000/metrics | grep '^taskflow_http_requests_total'
curl -s 127.0.0.1:9808/metrics | grep '^taskflow_celery_tasks_total'   # after Beat has run once
docker compose logs api --since 1m | grep '"logger": "app.requests"'
```

## Known limitations

- `/metrics` is unauthenticated. It is meant for Prometheus on the internal network; in a real
  deployment it should not be reachable from outside.
- The API container's healthcheck requests `/docs` every 30 s, which shows up as request records
  and in the `/docs` series. A dedicated `/health` endpoint (#127) should replace it and can be
  left out of the request logs.
- The worker's "Serving worker metrics" info line is logged before Celery has configured logging,
  so it does not appear. Check the endpoint itself instead.
- Beat does not run tasks, so it has no metrics endpoint.
- Celery's own "Task ... succeeded" line (`celery.app.trace`) includes the task's arguments and
  return value as strings. TaskFlow's tasks pass IDs only, but a task that took sensitive arguments
  would leak them there, because redaction only sees dict keys, not text inside a repr.
