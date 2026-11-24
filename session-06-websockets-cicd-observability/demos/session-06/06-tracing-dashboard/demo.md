# Demo 06 — Tracing and Dashboard

## Loom Video
Paste Loom link here.

## Objective
Show where the time goes in one request, across the API, the database and the Celery worker, and
show request rate, errors, latency and job outcomes on one dashboard under a controlled load.

## Scenario
"Assigning a task feels slow." The metrics say the assign route's p95 went up, but not why. A trace
of one assignment shows each SQL statement and the notification job it queued, and its trace id
leads to the exact log lines on both the API and the worker.

## Commands / Steps Used
```bash
make docker-up                 # adds tempo, prometheus and grafana to the stack
make flow-demo                 # one task assignment through the whole stack

# Grafana: http://127.0.0.1:3000 (TaskFlow overview is the home dashboard)
# Traces:  Explore > Tempo > TraceQL: {name="POST /api/v1/tasks/{task_id}/assign"}

# Join logs and traces by id
docker compose logs api --no-log-prefix | grep '"trace_id": "<trace id>"'
docker compose logs celery-worker --no-log-prefix | grep '<trace id>'

# Controlled load, then watch the dashboard
make load-test                 # 20 clients for 60 s against GET /api/v1/projects

# Prometheus targets
curl -s 127.0.0.1:9090/api/v1/targets
```

## Expected Behavior
- Prometheus scrapes both `api` and `celery-worker`; the dashboard and both data sources load
  without manual setup.
- One assignment produces a single trace with the request span, the `TaskService.assign_task`
  span, a span per SQL statement, and the Celery job queued by the API and run by the worker.
- The request's JSON log line carries the same `trace_id` as the trace.
- The load test meets the target: p95 ≤ 200 ms and errors ≤ 1%.

## Actual Findings
All of the above held on the local Docker stack (2026-11-15). The trace also showed that one
assignment runs 13 `SELECT` statements in the API, which is worth a look in a later session.

## Evidence
Prometheus targets and Grafana provisioning:
```text
api up
celery-worker up
dashboard: TaskFlow overview | panels: 10
datasources: ['Prometheus', 'Tempo']
```

Tempo search for the assign route (from `make flow-demo`):
```text
f59fc892b552243dff2dc089e6eccb3e taskflow-api POST /api/v1/tasks/{task_id}/assign 342 ms
```
(342 ms is the whole trace, including the worker job that ran after the response; the request
itself took 165 ms, as its log line below shows.)

Spans in that trace (33 in total, grouped by service and name):
```text
taskflow-api     POST /api/v1/tasks/{task_id}/assign x1
taskflow-api     TaskService.assign_task x1
taskflow-api     connect x2
taskflow-api     SELECT x13
taskflow-api     INSERT x3
taskflow-api     UPDATE x1
taskflow-api     apply_async/app.tasks.notification_tasks.send_task_assignment_notification x1
taskflow-api     POST /api/v1/tasks/{task_id}/assign http receive / http send x4
taskflow-worker  run/app.tasks.notification_tasks.send_task_assignment_notification x1
taskflow-worker  connect x1
taskflow-worker  SELECT x4
taskflow-worker  UPDATE x1
```

The request's log line, joined to the trace by id (3 worker log lines carry the same `trace_id`):
```json
{"timestamp": "2026-11-15T09:52:24.450+00:00", "level": "INFO", "logger": "app.requests", "message": "POST /api/v1/tasks/{task_id}/assign 200", "request_id": "c5eb1bcb0d11478fa453fa18aedc9ebc", "trace_id": "f59fc892b552243dff2dc089e6eccb3e", "span_id": "703441bf5dedecc7", "user_id": 13, "workspace_id": 1, "task_id": 202, "operation": "POST /api/v1/tasks/{task_id}/assign", "outcome": "success", "status": 200, "duration_ms": 165.36}
```

Load test (`make load-test`):
```text
GET http://localhost:8000/api/v1/projects with 20 clients for 60s ...
requests: 25236  (420.6/s)
latency ms: p50 41.4  p95 81.1  p99 169.6
errors: 0 (0.00%)  4xx: 0
target p95 <= 200 ms: met
target errors <= 1%: met
```
Prometheus over the same window: p95 96.2 ms, no 5xx. Recorded in
[`docs/session-06/slo-and-deliverables.md`](../../../docs/session-06/slo-and-deliverables.md).

Screenshots: add the trace view (Explore > Tempo) and the dashboard during the load test.

## What We Learned
Fill in after recording.

## Open Questions
- Should Redis task events carry a `traceparent` so their consumers join the request's trace?
- Is 13 `SELECT`s for one assignment expected, or an N+1 to fix?
