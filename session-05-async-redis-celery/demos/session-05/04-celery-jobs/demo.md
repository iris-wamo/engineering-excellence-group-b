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

Prove seven core production behaviors:
1. **Request-Path Decoupling**: Assigning a task persists the changes, then publishes the Celery job from a worker thread (`asyncio.to_thread`) with `retry=False` and 1s broker timeouts, so a slow or down broker never blocks the event loop.
2. **Worker Processing**: Celery worker picks up the job from Redis and transitions the database notification status from `pending` to `sent` with enriched payload metadata.
3. **Idempotency**: The job is keyed on its `notification_id` and locks that row (`SELECT ... FOR UPDATE`). Executing it multiple times never sends the row twice (`already_sent`, `idempotent: True`).
4. **Transient Failure Retry**: Network or database errors trigger automatic exponential backoff retries ($2^0, 2^1, 2^2\dots$) up to the limit (`max_retries=3`).
5. **Permanent Failure Handling**: Domain validation errors (non-existent task or recipient) fail immediately with zero retries, marking the notification `failed` in the database with the error recorded.
6. **Worker-Down Resilience**: When the worker is offline, assignment jobs queue safely in the Redis broker list (`celery`) and are processed once the worker resumes.
7. **Reassignment A → B → A**: Each assignment row is delivered exactly once. The second notification to A is sent, not skipped because of A's earlier `sent` row. A reassignment before delivery cancels the replaced assignee's pending row instead of letting it fail later (covered by integration tests).

---

## Scenario

A team lead assigns a high-priority task to a developer. The API must not wait on the broker.
Behind the scenes:
- A `pending` notification is recorded atomically with the task assignment in PostgreSQL.
- A Celery job `app.tasks.notification_tasks.send_task_assignment_notification` carrying that row's `notification_id` is queued in Redis broker.
- If the publish fails, the row stays `pending` and the Beat sweep `requeue_stale_assignment_notifications` re-publishes it.

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
*(Runs `scripts/demo_celery_jobs.py` demonstrating all 7 scenarios with timing, database checks, and error simulations).*

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
# Unit tests: exception hierarchy, backoff countdown, retry bounds, retry classification
uv run pytest tests/unit/test_celery_notification_tasks.py -v

# Integration tests: transaction safety, broker down, delivery, idempotency,
# A -> B -> A reassignment, outbox sweep
uv run pytest tests/integration/services/test_celery_assignment_flow.py -v
```

---

## Expected Behavior vs Actual Findings

| Scenario | Expected Behavior | Actual Finding | Result |
| :--- | :--- | :--- | :---: |
| **Non-blocking Dispatch** | Publish runs off the event loop; an unreachable broker fails fast. | Publish runs via `asyncio.to_thread`. Against an unroutable broker address it raised `OperationalError` after **1.05s** (4.07s before `broker_connection_timeout=1`). | **PASS** |
| **Worker Delivery** | Notification row transitions from `pending` to `sent` with delivery payload. | Worker updates status to `sent` with `payload: {"dispatched": true, "task_title": ...}`. | **PASS** |
| **Duplicate Delivery** | Second execution skips delivery, returns `already_sent`, count remains 1. | Returned `idempotent: True, status: already_sent`; DB count remains exactly 1. | **PASS** |
| **Transient Error** | Catches transient failure, schedules retry with exponential backoff. | `simulate_transient_failures=1` caught `Retry: Retry in 1s`, retry completed successfully. | **PASS** |
| **Permanent Error** | Non-retryable error terminates immediately with 0 retries; marked failed. | `NotificationNotFoundError` aborted with 0 retries. | **PASS** |
| **Worker Offline** | Messages accumulate safely in Redis list `celery` without loss. | `LLEN celery` increased by 1; the test message was drained afterwards. | **PASS** |
| **A → B → A Reassignment** | Second notification to A is delivered. | Rows for A: `[(9, 'sent'), (11, 'sent')]`. | **PASS** |

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
  • Task ID: 21 ('Notification Pipeline Task #3183')
  • Assignee ID: 2 (Alice Developer)
  • Assigner ID: 1 (Demo Lead)

>> Step 1: Assign Task via Service / API (Measure Dispatch Latency)
  • Task assigned to user 2
  • Request-path execution time: 139.38 ms
  • Background job queued off the event loop via enqueue_assignment_notification
  • Notification row in DB: ID=9, Status=pending

>> Step 2: Celery Worker Processes Notification Job
  • Worker execution result: {'notification_id': 9, 'task_id': 21, 'recipient_id': 2, 'status': 'sent', 'idempotent': False}
  • Updated DB Notification: ID=9, Status=sent
  • Stored Payload: {'task_id': 21, 'dispatched': True, 'task_title': 'Notification Pipeline Task #3183', 'assigned_by_id': 1}

>> Step 3: Idempotent Delivery Check (Duplicate Execution)
  • Second execution result: {'notification_id': 9, 'task_id': 21, 'recipient_id': 2, 'status': 'already_sent', 'idempotent': True}
  • Notification count in DB for (task=21, recipient=2): 1
  [PASS] Exactly 1 notification exists. Duplicate ignored safely.

>> Step 4: Transient Failure & Automatic Retry Simulation
  Simulating temporary network/database outage on attempt 1 (simulate_transient_failures=1)...
Temporary failure sending notification 9 (attempt 1/3): Simulated transient failure (attempt 1 of 1).. Retrying in 1s...
  • Celery caught transient failure: <class 'celery.exceptions.Retry'>: Retry in 1s: NotificationTransientError('Simulated transient failure (attempt 1 of 1).')
  • Automatic retry scheduled with backoff countdown
  [PASS] Transient failure triggers automatic retry.

>> Step 5: Permanent Failure (No Retries, Mark Failed)
  Testing permanent failure on invalid notification ID 999999...
Permanent failure for notification 999999: Notification with id 999999 not found.. Not retrying.
  • Caught non-retryable error: NotificationNotFoundError: Notification with id 999999 not found.
  • Celery aborted immediately without scheduling retry.
  [PASS] Permanent errors never retry.

>> Step 6: Worker-Down Resilience (Job Buffered in Broker)
  • Broker queue 'celery' initial length: 95
  • Enqueued delivery job for notification 9 into Redis broker
  • Broker queue 'celery' length now: 96
  [PASS] Job is safely preserved in Redis queue while worker is offline.
  • Drained test message from queue. Remaining: 95

>> Step 7: Reassignment A -> B -> A Delivers the New Notification
  • Assigned to user 3: {'notification_id': 10, 'task_id': 21, 'recipient_id': 3, 'status': 'sent', 'idempotent': False}
  • Assigned to user 2: {'notification_id': 11, 'task_id': 21, 'recipient_id': 2, 'status': 'sent', 'idempotent': False}
  • Rows for (task=21, recipient=2): [(9, 'sent'), (11, 'sent')]
  [PASS] Each assignment row is delivered exactly once.

===========================================================================
  All Celery Background Job Behaviors Verified Successfully!
===========================================================================
```

### Test Suite Execution Output

```text
$ uv run pytest tests/unit/test_celery_notification_tasks.py tests/integration/services/test_celery_assignment_flow.py -v

collected 30 items
tests/unit/test_celery_notification_tasks.py::test_exception_hierarchy PASSED [  3%]
tests/unit/test_celery_notification_tasks.py::test_task_configuration_attributes PASSED [  6%]
tests/unit/test_celery_notification_tasks.py::test_permanent_failure_does_not_retry PASSED [ 10%]
tests/unit/test_celery_notification_tasks.py::test_transient_failure_retries_with_backoff PASSED [ 13%]
tests/unit/test_celery_notification_tasks.py::test_operational_error_retries_with_backoff PASSED [ 16%]
tests/unit/test_celery_notification_tasks.py::test_transient_failure_exhausts_retries_and_marks_failed PASSED [ 20%]
tests/unit/test_celery_notification_tasks.py::test_non_transient_errors_are_not_retried_and_mark_failed[integrity-error] PASSED [ 23%]
tests/unit/test_celery_notification_tasks.py::test_non_transient_errors_are_not_retried_and_mark_failed[dbapi-error-not-invalidated] PASSED [ 26%]
tests/unit/test_celery_notification_tasks.py::test_non_transient_errors_are_not_retried_and_mark_failed[unexpected-error] PASSED [ 30%]
tests/unit/test_celery_notification_tasks.py::test_connection_level_errors_are_retried[dbapi-error-connection-invalidated] PASSED [ 33%]
tests/unit/test_celery_notification_tasks.py::test_connection_level_errors_are_retried[connection-refused] PASSED [ 36%]
tests/unit/test_celery_notification_tasks.py::test_connection_level_errors_are_retried[timeout] PASSED [ 40%]
tests/unit/test_celery_notification_tasks.py::test_process_assignment_notification_simulate_permanent_failure PASSED [ 43%]
tests/unit/test_celery_notification_tasks.py::test_process_assignment_notification_simulate_transient_failure PASSED [ 46%]
tests/integration/services/test_celery_assignment_flow.py::test_assign_task_triggers_celery_job PASSED [ 50%]
tests/integration/services/test_celery_assignment_flow.py::test_assign_task_broker_down_graceful_degradation PASSED [ 53%]
tests/integration/services/test_celery_assignment_flow.py::test_process_assignment_notification_success PASSED [ 56%]
tests/integration/services/test_celery_assignment_flow.py::test_process_assignment_notification_idempotent_duplicate PASSED [ 60%]
tests/integration/services/test_celery_assignment_flow.py::test_process_assignment_notification_entity_validations PASSED [ 63%]
tests/integration/services/test_celery_assignment_flow.py::test_mark_notification_failed PASSED [ 66%]
tests/integration/services/test_celery_assignment_flow.py::test_reassignment_back_to_earlier_assignee_delivers_new_notification PASSED [ 70%]
tests/integration/services/test_celery_assignment_flow.py::test_mark_notification_failed_only_touches_that_row PASSED [ 73%]
tests/integration/services/test_celery_assignment_flow.py::test_stale_pending_sweep_claims_only_old_pending_assignments PASSED [ 76%]
tests/integration/services/test_celery_assignment_flow.py::test_stale_pending_sweep_gives_up_after_max_attempts PASSED [ 80%]
tests/integration/services/test_celery_assignment_flow.py::test_requeue_stale_assignment_notifications_publishes_each_row PASSED [ 83%]
tests/integration/services/test_celery_assignment_flow.py::test_reassignment_cancels_previous_assignees_pending_notification PASSED [ 86%]
tests/integration/services/test_celery_assignment_flow.py::test_reassignment_keeps_already_sent_notification PASSED [ 90%]
tests/integration/services/test_celery_assignment_flow.py::test_unassignment_cancels_pending_notification PASSED [ 93%]
tests/integration/services/test_celery_assignment_flow.py::test_create_task_with_assignee_stages_and_dispatches_notification PASSED [ 96%]
tests/integration/services/test_celery_assignment_flow.py::test_create_task_without_assignee_has_no_notification PASSED [100%]

============================== 30 passed in 2.55s ==============================
```

---

## What We Learned

1. **Separation of Commit vs Dispatch**:
   Background jobs must be queued strictly **after** the primary database transaction commits. Dispatching inside an uncommitted transaction risks executing a background job against data that may roll back.
2. **At-Least-Once Delivery Requires Idempotency**:
   With `task_acks_late=True`, worker restarts or network partition redeliver messages. The idempotency key must be the specific outbox row (`notification_id`), not `(task_id, recipient_id)`: the broader key wrongly skipped the second notification when a task went A → B → A.
3. **Classifying Failures Prevents Waste**:
   Retrying invalid IDs or schema errors wastes worker cycles. Classifying exceptions into `NotificationTransientError` vs `NotificationPermanentError` guarantees that temporary blips self-heal while permanent bugs fail fast and are recorded for investigation.
4. **Resilience to Broker / Worker Outages**:
   Decoupling the HTTP response from the worker means that even if all Celery workers crash, user requests still succeed and jobs buffer in Redis until workers recover.

---

## Open Questions

- In Session 05 #102, Celery Beat gets a dedicated container in Docker Compose. Until then, run `make celery-beat` locally so the stale-pending outbox sweep runs.
- For dead-letter handling of permanently failed notification tasks: should exhausted retries publish to a dead-letter Redis Stream or remain recorded with `status='failed'` in PostgreSQL? *(Currently audited in PostgreSQL `notification` table with payload error field).*
