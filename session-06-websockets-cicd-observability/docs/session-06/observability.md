# Observability

How TaskFlow records what happened (logs), how much of it happened (metrics) and where the time
went (traces), and where to look at all three. Health checks and the incident simulation come in
#127.

## Overview

| Signal | Where it is produced | Where to read it |
|---|---|---|
| Request log record | `ObservabilityMiddleware` (`taskflow_shared/observability/`), one per HTTP request | API container stdout |
| Task log record | Celery signal handlers (`app/core/celery_app.py` → `app/observability/celery.py`), one per task run | Worker container stdout |
| API metrics | Same middleware, `prometheus_client` default registry | `GET /metrics` on the API (port 8000) |
| Worker metrics | Same signal handlers, multiprocess mode | `GET /metrics` on the worker, `127.0.0.1:9808` |
| Traces | OpenTelemetry in the API and the worker, exported over OTLP | Tempo, viewed in Grafana (Explore > Tempo) |
| Dashboard | Prometheus scrapes both metrics endpoints | Grafana, <http://127.0.0.1:3000> (TaskFlow overview) |

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
| `error_category` | ✓ | ✓ | exception handlers, middleware / `task_failure`, `task_retry` |
| `user_id` | when authenticated | via `request_id` (see below) | `get_current_user`, `get_optional_current_user` |
| `workspace_id` | when resolved | via `request_id` (see below) | `get_current_workspace_id` |
| `project_id`, `task_id` | from the path, when present | | middleware |
| `task_name`, `celery_task_id` | | ✓ (named so it never clashes with the TaskFlow `task_id`) | signal handler |
| `retries` | | ✓ | signal handler |
| `exc_type`, `exc_info` | on an unhandled error (the request record carries the traceback) | on `logger.exception` | `JsonFormatter` |

`error_category` follows one rule everywhere (`taskflow_shared.logging.error_category`): the error
envelope code for app errors (`not_found`, `validation_error`), otherwise the exception class in
snake_case (`runtime_error`, `connection_error`, `gaierror`). For a Celery retry it is the error
that caused the retry, not Celery's `Retry` wrapper.

An unhandled error is logged once, on the request's own record, so its traceback carries the
request's `user_id` and `workspace_id`. The catch-all error handler sees the error is already
logged and does not log it again. If the error happens after the response started (a streamed
body), the record keeps the status the client received and is marked `server_error`.

Any other log call in the app picks up the same bound fields, so a warning logged deep in a
service during a request also has `user_id`, `workspace_id` and `request_id`.

Task records don't carry `user_id`, `workspace_id` or `project_id`. The jobs receive only IDs of
their own (`send_task_assignment_notification` gets `notification_id`; the Beat sweeps get
nothing), so the worker would need a database lookup just to label its logs. The link back is
`request_id`: a job queued by a request carries that request's id, and the request record has the
user, workspace and project. Beat jobs have `request_id: null`, as they belong to no request.

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
- Celery's own "received" and "succeeded" records carry the task's arguments and return value; the
  worker replaces them with `[omitted]` in both the extra fields and the message.
- Masking applies to both formats: `LOG_FORMAT=text` wraps the text formatter (the worker's Celery
  formatter included), so the message and traceback are masked there too.

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
router (`/projects/{project_id}`), not the `/api/v1` prefix. The full template, prefix params
included, is on FastAPI's effective route context in the scope, which the middleware uses
(converters such as `{item_id:int}` are written as `{item_id}`). It is a private scope entry; if a
FastAPI upgrade removes it, labels fall back to the route's own path and lose the prefix, rather
than growing without bound. Plain routes like `/docs` have no route context and are found by
their endpoint.

An earlier version rebuilt the prefix by subtracting the filled-in route from the request path.
Review showed it broke on prefixes with path params (every ID became a label) and on converted
params, so it was replaced.

### Why the worker serves its own metrics

The Celery worker runs tasks in forked child processes, each with its own memory, so each child
would count only its own runs, and no single process could report the total. The worker uses
`prometheus_client` multiprocess mode instead:

- `PROMETHEUS_MULTIPROC_DIR` is set for the worker (Compose: `/tmp/prometheus-worker` in the
  worker's own container; `make celery-worker`: a fresh `mktemp -d` directory per run). Children
  write their values to files there. The directory must not be shared: a second worker would clear
  the first one's files.
- On `worker_init` the main process clears files left by an earlier run, then serves the sum of all
  files on `WORKER_METRICS_ADDR:WORKER_METRICS_PORT` (default `127.0.0.1:9808`). Compose sets the
  address to `0.0.0.0` inside the container so Prometheus can reach it, and publishes the port on
  the host's `127.0.0.1` only.
- If the variable is not set, the worker logs a warning and serves nothing, rather than serving
  numbers that silently miss the children's work.

The API runs as one uvicorn process, so it uses the default registry. Running uvicorn with several
workers would need the same multiprocess setup there.

**Rejected alternative: Flower's `/metrics`.** Flower already exports task events as Prometheus
metrics, so it would have needed no code. It was not used because its numbers come from the Celery
events Flower asks workers to send while it is connected: if Flower is down or restarts, runs in
that window are never counted. The worker's own counters do not depend on another process being up.
Both can run side by side.

## Traces

`make docker-up` starts **Tempo**, which receives spans over OTLP (HTTP, port 4318). There is no
separate tracing UI: traces are viewed and searched in Grafana, under Explore with the Tempo data
source (search by service, span name or duration with TraceQL, or paste a `trace_id` from a log
line).

What produces spans:

| Span | From |
|---|---|
| `POST /api/v1/tasks/{task_id}/assign` (the request) | `FastAPIInstrumentor` (`app/observability/tracing.py`) |
| `TaskService.create_task`, `.update_task_status`, `.assign_task` | `@traced` from `taskflow_shared.observability` |
| One span per SQL statement (`db.statement` attribute) | `SQLAlchemyInstrumentor` |
| `apply_async/...` in the API, `run/...` in the worker | `CeleryInstrumentor` |

`/metrics`, `/docs` and `/openapi.json` are not traced (scrapes and the container healthcheck).

Setup is `configure_tracing(service_name)` in the shared package. It reads the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` (set to `http://tempo:4318` for the api and worker in Compose) and
does nothing when it is unset, so tests and plain local runs don't need a collector. `make run`
outside Docker can send to the published `127.0.0.1:4318` by exporting that variable.

**Logs and traces are joined by id.** Every JSON log line written inside a span has `trace_id` and
`span_id`, in the same hex format Grafana shows, so a request record leads to its trace and a trace
to its log lines.

**Engines are created through `sqlalchemy.ext.asyncio`.** The SQLAlchemy instrumentation works by
wrapping `sqlalchemy.ext.asyncio.create_async_engine`. Code that did
`from sqlalchemy.ext.asyncio import create_async_engine` at import time kept the unwrapped function,
so `app/db/session.py`, `app/tasks/db.py` and the per-test engine call it through the module.

### Across the async boundaries

| Boundary | Same trace? | Why |
|---|---|---|
| API request → Celery job (assignment notification) | **Yes** | `CeleryInstrumentor` writes the trace context into the job's message headers when the API queues it, and the worker continues that trace. The worker sets up tracing in `worker_process_init`, after the fork, because the exporter's background thread does not survive forking. |
| API request → Redis task events (Pub/Sub, Streams) | **No** | The event payload (`TaskEvent`) has no trace context, and the consumers are separate processes. Carrying it would mean adding a `traceparent` field to the event schema and continuing it in the consumers. Not done: the events are fire-and-forget notifications today, and the `request_id` and `task_id` already link them to the request in the logs. |
| Celery Beat → scheduled jobs | Starts a new trace per run | Nothing upstream to continue. |

## Dashboard

Prometheus (`127.0.0.1:9090`) scrapes `api:8000/metrics` and `celery-worker:9808` every 5 s
(`docker/prometheus/prometheus.yml`). Grafana (`127.0.0.1:3000`) is provisioned from
`docker/grafana/`: the Prometheus and Tempo data sources and the **TaskFlow overview** dashboard,
which is also the home page. Anonymous visitors can view it and use Explore; it is bound to
localhost only.

| Panel | Query (simplified) |
|---|---|
| Requests / s | `sum(rate(taskflow_http_requests_total[1m]))` |
| 5xx error rate | 5xx requests over all requests, last minute |
| p95 latency | `histogram_quantile(0.95, …duration_seconds_bucket[5m])` |
| WebSocket connections | `sum(taskflow_websocket_connections)` (empty until #120 is merged) |
| Request rate, p95 latency and 4xx/5xx by route | the same, `by (route)` |
| Celery task runs by outcome | `increase(taskflow_celery_tasks_total[5m])` by task and outcome |
| Celery task p95 duration | `histogram_quantile(0.95, …task_duration_seconds_bucket[5m])` by task |
| Scrape targets up | `up` |

To change the dashboard, edit it in Grafana, export the JSON and replace
`docker/grafana/dashboards/taskflow.json`; provisioned dashboards can't be saved from the UI.

## Trying it

```bash
make docker-up
curl -s localhost:8000/api/v1/projects > /dev/null
curl -s localhost:8000/api/v1/projects/999999 > /dev/null
curl -s localhost:8000/metrics | grep '^taskflow_http_requests_total'
curl -s 127.0.0.1:9808/metrics | grep '^taskflow_celery_tasks_total'   # after Beat has run once
docker compose logs api --since 1m | grep '"logger": "app.requests"'
make load-test                 # 20 clients for 60 s against GET /api/v1/projects
open http://127.0.0.1:3000     # dashboard; Explore > Tempo for traces
```

## Known limitations

- `/metrics` is open unless `METRICS_TOKEN` is set; then Prometheus must send it as a bearer token
  (`authorization` in its scrape config). Set it wherever the API port is reachable from outside
  the internal network. Locally it stays open for convenience.
- The API container's healthcheck requests `/docs` every 30 s, which shows up as request records
  and in the `/docs` series. A dedicated `/health` endpoint (#127) should replace it and can be
  left out of the request logs.
- The worker's "Serving worker metrics" info line is logged before Celery has configured logging,
  so it does not appear. Check the endpoint itself instead.
- Beat does not run tasks, so it has no metrics endpoint.
- `LOG_LEVEL` (any case) sets the API's level. The worker's level comes from its `-l` flag.
