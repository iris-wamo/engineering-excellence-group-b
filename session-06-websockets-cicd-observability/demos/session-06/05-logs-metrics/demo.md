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
All of the above held on the local Docker stack. Issues found while building and reviewing it, all
fixed before this capture:
- With FastAPI's nested routers, the matched route only knows `/projects/{project_id}`, so the
  `/api/v1` prefix was missing from the label. The full template now comes from FastAPI's route
  context.
- `/docs` (hit by the container healthcheck) was labelled `<unmatched>` because FastAPI does not
  record plain routes in the scope. It is now found by endpoint.
- Worker records used `task_id` for the Celery job id while request records use it for the
  TaskFlow task, so a search for `task_id=201` missed the worker side. Worker records now use
  `celery_task_id`.
- Retries logged `error_category: "Retry"` because Celery's retry signal passes its own wrapper.
  The category is now the underlying error (`gaierror` when Postgres was stopped).
- Database errors were categorised by SQLAlchemy's docs-link code (`IntegrityError.code` is
  `"gkpj"`). Only app errors' codes are used now, so it is `integrity_error`.

## Evidence
Captured on 2026-11-18 from the final code, on the local Docker stack.

Request records (API container):
```json
{"timestamp": "2026-11-18T11:54:34.396+00:00", "level": "INFO", "logger": "app.requests", "message": "GET /api/v1/projects 200", "request_id": "f13116dbec07498aa3ec14784e5964ba", "workspace_id": 1, "operation": "GET /api/v1/projects", "outcome": "success", "status": 200, "duration_ms": 144.12}
{"timestamp": "2026-11-18T11:54:34.421+00:00", "level": "INFO", "logger": "app.requests", "message": "GET /api/v1/projects/{project_id} 404", "request_id": "0b590de81bdf49948de1bfae0600a3d3", "workspace_id": 1, "error_category": "not_found", "project_id": 999999, "operation": "GET /api/v1/projects/{project_id}", "outcome": "client_error", "status": 404, "duration_ms": 4.67}
{"timestamp": "2026-11-18T11:54:34.467+00:00", "level": "INFO", "logger": "app.requests", "message": "GET <unmatched> 404", "request_id": "2c71c4d4249045a7845097827118d2d1", "error_category": "not_found", "operation": "GET <unmatched>", "outcome": "client_error", "status": 404, "duration_ms": 31.32}
```

API `/metrics` (`/docs` is the container healthcheck):
```text
taskflow_http_requests_total{method="GET",route="/docs",status="200"} 5.0
taskflow_http_requests_total{method="GET",route="/api/v1/projects",status="200"} 1.0
taskflow_http_requests_total{method="GET",route="/api/v1/projects/{project_id}",status="404"} 1.0
taskflow_http_requests_total{method="GET",route="<unmatched>",status="404"} 1.0
```

One assignment followed from the API into the worker by its request id (`make flow-demo`):
```json
{"timestamp": "2026-11-18T11:54:41.483+00:00", "level": "INFO", "logger": "app.requests", "message": "POST /api/v1/tasks/{task_id}/assign 200", "request_id": "16a10a7a0dea4fcc920893309859b30a", "user_id": 15, "workspace_id": 1, "task_id": 203, "operation": "POST /api/v1/tasks/{task_id}/assign", "outcome": "success", "status": 200, "duration_ms": 103.06}
{"timestamp": "2026-11-18T11:54:41.578+00:00", "level": "INFO", "logger": "app.tasks.notification_tasks", "message": "Transitioned pending notification 283 to 'sent' for task 203 to recipient 16.", "request_id": "16a10a7a0dea4fcc920893309859b30a", "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "07012e75-9ce1-4b9f-b6ae-b813bf6d91bf"}
{"timestamp": "2026-11-18T11:54:41.581+00:00", "level": "INFO", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification succeeded", "request_id": "16a10a7a0dea4fcc920893309859b30a", "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "07012e75-9ce1-4b9f-b6ae-b813bf6d91bf", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "succeeded", "retries": 0, "duration_ms": 91.33}
```

A job sent with wrong arguments fails with `type_error`:
```json
{"timestamp": "2026-11-18T11:55:25.857+00:00", "level": "ERROR", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification failed", "request_id": null, "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "24cecd6a-7c04-4dcd-a7b4-5b21de3ed8a6", "error_category": "type_error", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "failed", "retries": 0, "duration_ms": 39.17}
```

A job sent while Postgres was stopped for 2 s retries on `gaierror`, then, with the database back,
fails for good on a permanent error (the notification id it was given doesn't exist), without
using its last retry:
```json
{"timestamp": "2026-11-18T11:55:31.285+00:00", "level": "INFO", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification retried", "request_id": null, "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "e037783a-2cb4-48bb-9862-4fe74b70a6cf", "error_category": "gaierror", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "retried", "retries": 0, "duration_ms": 271.5}
{"timestamp": "2026-11-18T11:55:32.284+00:00", "level": "INFO", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification retried", "request_id": null, "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "e037783a-2cb4-48bb-9862-4fe74b70a6cf", "error_category": "gaierror", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "retried", "retries": 1, "duration_ms": 25.51}
{"timestamp": "2026-11-18T11:55:34.387+00:00", "level": "ERROR", "logger": "app.tasks", "message": "app.tasks.notification_tasks.send_task_assignment_notification failed", "request_id": null, "task_name": "app.tasks.notification_tasks.send_task_assignment_notification", "celery_task_id": "e037783a-2cb4-48bb-9862-4fe74b70a6cf", "error_category": "invalid_assignment_notification_error", "operation": "app.tasks.notification_tasks.send_task_assignment_notification", "outcome": "failed", "retries": 2, "duration_ms": 108.26}
```

Worker `/metrics` after the above (Beat's sweeps included):
```text
taskflow_celery_tasks_total{outcome="succeeded",task="app.tasks.notification_tasks.requeue_stale_assignment_notifications"} 1.0
taskflow_celery_tasks_total{outcome="succeeded",task="app.tasks.reminder_tasks.send_due_task_reminders"} 4.0
taskflow_celery_tasks_total{outcome="succeeded",task="app.tasks.notification_tasks.send_task_assignment_notification"} 1.0
taskflow_celery_tasks_total{outcome="failed",task="app.tasks.notification_tasks.send_task_assignment_notification"} 2.0
taskflow_celery_tasks_total{outcome="retried",task="app.tasks.notification_tasks.send_task_assignment_notification"} 2.0
```

## What We Learned
Fill in after recording.

## Open Questions
- Should `/metrics` be served on a separate internal port instead of the public API port?
- How long should request records be kept, given they contain user and workspace IDs?
