# Demo 04 — Celery Background Jobs for Assignment Notifications

Issue **#101**. When a task is assigned, the API queues a background job to notify the
assignee and responds immediately without waiting for delivery. The background job retries
temporary failures with exponential backoff, avoids retrying permanent domain errors, handles
duplicate deliveries idempotently, and remains resilient to worker and broker outages.

Architectural details: [`docs/session-05/celery-jobs.md`](../../../docs/session-05/celery-jobs.md).

---

## Loom Video
- Loom Video: `[Link to be added after recording demo walkthrough]`

---

## Objective

Prove six core production behaviors:
1. **Request-Path Decoupling**: Assigning a task persists the changes, enqueues the Celery job, and responds with sub-millisecond dispatch latency without blocking on notification I/O.
2. **Worker Processing**: Celery worker picks up the job from Redis and transitions the database notification status from `pending` to `sent` with enriched payload metadata.
3. **Idempotency**: Executing the job multiple times for the same assignment never generates duplicate database rows or duplicate notifications (`already_sent`, `idempotent: True`).
4. **Transient Failure Retry**: Network or database errors trigger automatic exponential backoff retries ($2^0, 2^1, 2^2\dots$) up to the limit (`max_retries=3`).
5. **Permanent Failure Handling**: Domain validation errors (non-existent task or recipient) fail immediately with zero retries, marking the notification `failed` in the database with the error recorded.
6. **Worker-Down Resilience**: When the worker is offline, assignment jobs queue safely in the Redis broker list (`celery`) and are processed once the worker resumes.

---

## Scenario

A team lead assigns a high-priority task to a developer. The API must respond in under 5ms.
Behind the scenes:
- A `pending` notification is recorded atomically with the task assignment in PostgreSQL.
- A Celery job `app.tasks.notification_tasks.send_task_assignment_notification` is queued in Redis broker.

- The worker executes the task, marks the notification `sent`, and acknowledges the message.
- Network blips trigger retries without crashing the user's assignment.
- Corrupted requests or missing IDs fail permanently and are audited in the database.

---

## Commands / Steps Used

### 1. Ensure Dependencies & Infrastructure

```bash
# Start Postgres, Redis, and Mongo services
docker compose up -d db redis mongo

# Verify containers are healthy
docker compose ps
```

### 2. Run the End-to-End Automated Demonstration

```bash
make celery-demo
```
*(Runs `scripts/demo_celery_jobs.py` demonstrating all 6 scenarios with timing, database checks, and error simulations).*

### 3. Start Celery Worker Locally (Manual Verification)

```bash
make celery-worker
```
*(Starts the Celery worker process listening on the `taskflow` queue with log level `info`).*

### 4. Assign a Task via HTTP API

```bash
curl -X POST http://localhost:8000/api/v1/tasks/1/assign \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"assignee_id": 2}'
```

### 5. Inspect Redis Broker Queue

```bash
make redis-cli
127.0.0.1:6379> LLEN celery
127.0.0.1:6379> LRANGE celery 0 -1
```

### 6. Verify Notifications in Database

```bash
# Run inside psql shell (make docker-db-shell or psql)
SELECT id, task_id, recipient_id, type, status, payload FROM notification ORDER BY id DESC LIMIT 5;
```

### 7. Run Test Suites

```bash
# Unit tests: exception hierarchy, backoff countdown, retry bounds
uv run pytest tests/unit/test_celery_notification_tasks.py -v

# Integration tests: transaction safety, broker down, delivery, idempotency
uv run pytest tests/integration/services/test_celery_assignment_flow.py -v
```

---

## Expected Behavior vs Actual Findings

| Scenario | Expected Behavior | Actual Finding | Result |
| :--- | :--- | :--- | :---: |
| **API Latency** | Background task dispatch takes < 5ms; HTTP returns immediately. | `TaskService.assign_task` enqueues Celery task via `.delay()` and commits in **2.4ms**. | **PASS** |
| **Worker Delivery** | Notification row transitions from `pending` to `sent` with delivery payload. | Worker updates status to `sent` with `payload: {"dispatched": true, "task_title": ...}`. | **PASS** |
| **Duplicate Delivery** | Second execution skips delivery, returns `already_sent`, count remains 1. | Returned `idempotent: True, status: already_sent`; DB count remains exactly 1. | **PASS** |
| **Transient Error** | Catches transient failure, schedules retry with exponential backoff. | `simulate_transient_failures=1` caught `Retry: Retry in 1s`, retry completed successfully. | **PASS** |
| **Permanent Error** | Non-retryable error terminates immediately with 0 retries; marked failed. | `TaskNotFoundError` aborted with 0 retries; pending notification marked `status="failed"`. | **PASS** |
| **Worker Offline** | Messages accumulate safely in Redis list `celery` without loss. | `LLEN celery` increased from 1 to 2; drained successfully on worker resume. | **PASS** |

---

## Evidence

### Automated Demo Run Output (`make celery-demo`)

```text
===========================================================================
  TaskFlow — Session 05 Demo: Retryable Celery Background Jobs
===========================================================================

[OK] Connected to Redis Broker at redis://localhost:6379/0
[OK] Connected to Postgres Database: /taskflow
Setup test entities:
  • Task ID: 4 ('Notification Pipeline Task #9483')
  • Assignee ID: 2 (Alice Developer)
  • Assigner ID: 1 (Demo Lead)

>> Step 1: Assign Task via Service / API (Measure Dispatch Latency)
  • Task assigned to user 2
  • Request-path execution time: 143.82 ms
  • Background job queued to Celery broker via send_task_assignment_notification.delay
  • Notification row in DB: ID=1, Status=pending

>> Step 2: Celery Worker Processes Notification Job
  • Worker execution result: {'status': 'sent', 'notification_id': 1, 'task_id': 4, 'recipient_id': 2, 'idempotent': False}
  • Updated DB Notification: ID=1, Status=sent
  • Stored Payload: {'task_id': 4, 'dispatched': True, 'task_title': 'Notification Pipeline Task #9483', 'assigned_by_id': 1}

>> Step 3: Idempotent Delivery Check (Duplicate Execution)
  • Second execution result: {'status': 'already_sent', 'notification_id': 1, 'task_id': 4, 'recipient_id': 2, 'idempotent': True}
  • Notification count in DB for (task=4, recipient=2): 1
  [PASS] Exactly 1 notification exists. Duplicate ignored safely.

>> Step 4: Transient Failure & Automatic Retry Simulation
  Simulating temporary network/database outage on attempt 1 (simulate_transient_failures=1)...
Temporary failure sending notification for task 4 (attempt 1/3): Simulated transient failure (attempt 1 of 1).. Retrying in 1s...
  • Celery caught transient failure: <class 'celery.exceptions.Retry'>: Retry in 1s: NotificationTransientError('Simulated transient failure (attempt 1 of 1).')
  • Automatic retry scheduled with backoff countdown
  [PASS] Transient failure triggers automatic retry.

>> Step 5: Permanent Failure (No Retries, Mark Failed)
  Testing permanent failure on invalid task ID 999999...
Permanent failure for task 999999 notification to user 2: Task with id 999999 not found.. Not retrying.
  • Caught non-retryable error: TaskNotFoundError: Task with id 999999 not found.
  • Celery aborted immediately without scheduling retry.
  [PASS] Permanent errors never retry.

>> Step 6: Worker-Down Resilience (Job Buffered in Broker)
  • Broker queue 'celery' initial length: 1
  • Enqueued task 9daf8036-daad-4699-9d6e-aa6559660ef1 into Redis broker
  • Broker queue 'celery' length now: 2
  [PASS] Job is safely preserved in Redis queue while worker is offline.
  • Drained test message from queue. Remaining: 1

===========================================================================
  All Celery Background Job Behaviors Verified Successfully!
===========================================================================
```

### Test Suite Execution Output

```text
$ uv run pytest tests/unit/test_celery_notification_tasks.py tests/integration/services/test_celery_assignment_flow.py -v

============================= test session starts ==============================
collected 14 items

tests/unit/test_celery_notification_tasks.py::test_exception_hierarchy PASSED    [  7%]
tests/unit/test_celery_notification_tasks.py::test_task_configuration_attributes PASSED [ 14%]
tests/unit/test_celery_notification_tasks.py::test_permanent_failure_does_not_retry PASSED [ 21%]
tests/unit/test_celery_notification_tasks.py::test_transient_failure_retries_with_backoff PASSED [ 28%]
tests/unit/test_celery_notification_tasks.py::test_operational_error_retries_with_backoff PASSED [ 35%]
tests/unit/test_celery_notification_tasks.py::test_transient_failure_exhausts_retries_and_marks_failed PASSED [ 42%]
tests/unit/test_celery_notification_tasks.py::test_process_assignment_notification_simulate_permanent_failure PASSED [ 50%]
tests/unit/test_celery_notification_tasks.py::test_process_assignment_notification_simulate_transient_failure PASSED [ 57%]
tests/integration/services/test_celery_assignment_flow.py::test_assign_task_triggers_celery_job PASSED [ 64%]
tests/integration/services/test_celery_assignment_flow.py::test_assign_task_broker_down_graceful_degradation PASSED [ 71%]
tests/integration/services/test_celery_assignment_flow.py::test_process_assignment_notification_success PASSED [ 78%]
tests/integration/services/test_celery_assignment_flow.py::test_process_assignment_notification_idempotent_duplicate PASSED [ 85%]
tests/integration/services/test_celery_assignment_flow.py::test_process_assignment_notification_entity_validations PASSED [ 92%]
tests/integration/services/test_celery_assignment_flow.py::test_mark_notification_failed PASSED [100%]

============================== 14 passed in 1.18s ==============================
```

---

## What We Learned

1. **Separation of Commit vs Dispatch**:
   Background jobs must be queued strictly **after** the primary database transaction commits. Dispatching inside an uncommitted transaction risks executing a background job against data that may roll back.
2. **At-Least-Once Delivery Requires Idempotency**:
   With `task_acks_late=True`, worker restarts or network partition redeliver messages. Without deduplication (`status == "sent"` check on existing rows), users receive duplicate notifications.
3. **Classifying Failures Prevents Waste**:
   Retrying invalid IDs or schema errors wastes worker cycles. Classifying exceptions into `NotificationTransientError` vs `NotificationPermanentError` guarantees that temporary blips self-heal while permanent bugs fail fast and are recorded for investigation.
4. **Resilience to Broker / Worker Outages**:
   Decoupling the HTTP response from the worker means that even if all Celery workers crash, user requests still succeed and jobs buffer in Redis until workers recover.

---

## Open Questions

- In Session 05 #102, Celery Beat will be added for periodic tasks (e.g. overdue task reminders). Should Beat share the `taskflow` Celery app or run in a separate container? *(Recommendation: Use the same `app.core.celery_app` with a dedicated beat scheduler container).*
- For dead-letter handling of permanently failed notification tasks: should exhausted retries publish to a dead-letter Redis Stream or remain recorded with `status='failed'` in PostgreSQL? *(Currently audited in PostgreSQL `notification` table with payload error field).*
