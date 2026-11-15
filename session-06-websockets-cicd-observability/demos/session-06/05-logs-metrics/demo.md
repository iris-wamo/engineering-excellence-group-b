# Demo 05 — Structured Logs and Metrics

## Loom Video
Paste Loom link here.

## Objective
Show that every API request and every Celery task run leaves one JSON log record with who, what,
outcome and duration, and that Prometheus metrics count requests and task runs without unbounded
labels or leaked credentials.

## Scenario
Support gets "projects page fails for me". Without user and workspace IDs on the request record,
and without a per-route error rate, nobody can tell whether it is one user, one workspace, or every
request to that route.

## Commands / Steps Used
```bash
make docker-up

# A success, a domain error, and a path that matches no route
curl -s localhost:8000/api/v1/projects > /dev/null
curl -s localhost:8000/api/v1/projects/999999 > /dev/null
curl -s localhost:8000/nope/123 > /dev/null

# Request records
docker compose logs api --since 1m | grep '"logger": "app.requests"'

# API metrics
curl -s localhost:8000/metrics | grep -E '^taskflow_http_requests_total|^taskflow_http_request_duration_seconds_count'

# Worker metrics and task records (Beat runs the reminder sweep every minute)
curl -s 127.0.0.1:9808/metrics | grep '^taskflow_celery_tasks_total'
docker compose logs celery-worker --since 2m | grep '"logger": "app.tasks"'

# Redaction and label tests
uv run pytest packages/taskflow_shared/tests/test_structured_logging.py tests/unit/observability tests/integration/api/test_request_logging.py
```

## Expected Behavior
- One request record per call, with `operation` as the route template, `outcome`, `status`,
  `duration_ms`, `workspace_id`, and `project_id`/`error_category` where they apply.
- `/metrics` groups requests by route template; unknown paths share `<unmatched>`.
- Worker metrics count runs from all pool processes on port 9808.
- No token or password value appears in any record.

## Actual Findings
All of the above held on the local Docker stack. Two issues were found while running it, both
fixed before this demo:
- With FastAPI's nested routers, the matched route only knew `/projects/{project_id}`, so the
  `/api/v1` prefix was missing from the label. The middleware now rebuilds the prefix.
- `/docs` (hit by the container healthcheck) was labelled `<unmatched>` because FastAPI does not
  record plain routes in the scope. It is now found by endpoint.
- Worker records used `task_id` for the Celery job id while request records use it for the
  TaskFlow task, so a search for `task_id=201` missed the worker side. Worker records now use
  `celery_task_id`.
- Retries logged `error_category: "Retry"` because Celery's retry signal passes its own wrapper.
  The category is now the underlying error (`gaierror` when Postgres was stopped).

## Evidence
Request records (API container, local Docker stack):
```json
{"timestamp": "2026-11-13T13:25:36.913+00:00", "level": "INFO", "logger": "app.requests", "message": "GET /api/v1/projects 200", "request_id": "46a08d5794364b98be0d3a535efed50f", "workspace_id": 1, "operation": "GET /api/v1/projects", "outcome": "success", "status": 200, "duration_ms": 120.65}
{"timestamp": "2026-11-13T13:25:36.926+00:00", "level": "INFO", "logger": "app.requests", "message": "GET /api/v1/projects/{project_id} 404", "request_id": "209b26a5f12f429db105b56af83f4d86", "workspace_id": 1, "error_category": "not_found", "project_id": 999999, "operation": "GET /api/v1/projects/{project_id}", "outcome": "client_error", "status": 404, "duration_ms": 2.61}
{"timestamp": "2026-11-13T13:25:36.949+00:00", "level": "INFO", "logger": "app.requests", "message": "GET <unmatched> 404", "request_id": "123b665ecb034d21b17ba94894cd4374", "error_category": "not_found", "operation": "GET <unmatched>", "outcome": "client_error", "status": 404, "duration_ms": 13.08}
```

API `/metrics`:
```text
taskflow_http_requests_total{method="GET",route="/api/v1/projects",status="200"} 1.0
taskflow_http_requests_total{method="GET",route="/api/v1/projects/{project_id}",status="404"} 1.0
taskflow_http_requests_total{method="GET",route="<unmatched>",status="404"} 1.0
taskflow_http_requests_total{method="GET",route="/docs",status="200"} 3.0
```

Worker `/metrics` (about 38 minutes after the worker started; Beat sends the reminder sweep every
60 s and the outbox sweep every 300 s):
```text
taskflow_celery_tasks_total{outcome="succeeded",task="app.tasks.reminder_tasks.send_due_task_reminders"} 36.0
taskflow_celery_tasks_total{outcome="succeeded",task="app.tasks.notification_tasks.requeue_stale_assignment_notifications"} 7.0
taskflow_celery_task_duration_seconds_bucket{le="0.1",task="app.tasks.reminder_tasks.send_due_task_reminders"} 26.0
taskflow_celery_task_duration_seconds_bucket{le="0.25",task="app.tasks.reminder_tasks.send_due_task_reminders"} 35.0
```

One assignment followed from the API into the worker by its request id (`make flow-demo`):
```json
{"timestamp": "2026-11-15T08:44:17.543+00:00", "level": "INFO", "logger": "app.requests", "message": "POST /api/v1/tasks/{task_id}/assign 200", "request_id": "24f509cc119b4b2db902e2bcefb10b52", "user_id": 11, "workspace_id": 1, "task_id": 201, "operation": "POST /api/v1/tasks/{task_id}/assign", "outcome": "success", "status": 200, "duration_ms": 300.13}
{"timestamp": "2026-11-15T08:44:17.634+00:00", "level": "INFO", "logger": "app.tasks.notification_tasks", "message": "Transitioned pending notification 241 to 'sent' for task 201 to recipient 12.", "request_id": "24f509cc119b4b2db902e2bcefb10b52", "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "task_id": "8056d40b-7c5d-4cca-9603-4a8026c4414e"}
```
(This run was before the `celery_task_id` rename; the second line's `task_id` is the Celery job id.)

A failed job (wrong arguments) and a retried one (Postgres stopped for 2 s, then started):
```text
taskflow_celery_tasks_total{outcome="failed",task="app.tasks.notification_tasks.send_task_assignment_notification"} 1.0
taskflow_celery_tasks_total{outcome="retried",task="app.tasks.notification_tasks.send_task_assignment_notification"} 2.0
taskflow_celery_tasks_total{outcome="succeeded",task="app.tasks.notification_tasks.send_task_assignment_notification"} 1.0
```
```json
{"timestamp": "2026-11-15T08:46:12.333+00:00", "level": "ERROR", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification failed", "request_id": null, "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "de625f4e-d013-4b15-82d8-a23c878ab6cd", "error_category": "TypeError", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "failed", "retries": 0, "duration_ms": 27.0}
{"timestamp": "2026-11-15T08:47:24.965+00:00", "level": "INFO", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification retried", "request_id": null, "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "7e39f742-80b5-41d3-b589-84e180cedcc3", "error_category": "gaierror", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "retried", "retries": 0, "duration_ms": 102.66}
{"timestamp": "2026-11-15T08:47:28.086+00:00", "level": "INFO", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification succeeded", "request_id": null, "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "7e39f742-80b5-41d3-b589-84e180cedcc3", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "succeeded", "retries": 2, "duration_ms": 125.37}
```

## What We Learned
Fill in after recording.

## Open Questions
- Should `/metrics` be served on a separate internal port instead of the public API port?
- How long should request records be kept, given they contain user and workspace IDs?
