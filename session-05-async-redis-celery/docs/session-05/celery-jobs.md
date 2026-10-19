# Retryable Celery Background Jobs for Task Assignment Notifications

Issue **#101**. When a task is assigned or reassigned in TaskFlow, the assignee must be notified.
Delivery of notifications (database writes, emails, push notifications) is prone to transient
network issues, service degradation, and latency spikes.

This document details the architecture, retry policies, idempotency guarantees, and failure
resilience strategies for moving notification delivery out of the HTTP request path into
asynchronous, retryable Celery background jobs backed by Redis.

---

## 1. Request-Path Offloading: Why and How

### The Problem with In-Band Notifications
When notifications are delivered synchronously within an API endpoint:
1. **Request Latency**: The user waits for external network roundtrips, database operations, or email gateways before getting a response.
2. **Coupled Fate**: A temporary timeout or error during notification delivery can crash the entire request, causing a valid task assignment transaction to roll back or error out.
3. **Connection Starvation**: Long-running synchronous I/O keeps web worker threads or async event loop connections occupied, reducing API throughput.

### The Solution: Asynchronous Background Offloading
TaskFlow decouples task state mutations from notification delivery:
1. The API transaction validates membership, updates the task row, records assignment history, and writes a `pending` notification row in PostgreSQL.
2. The transaction commits to PostgreSQL.
3. Immediately **after commit**, the API publishes a background job carrying only the row's `notification_id` (`enqueue_assignment_notification`, which calls `apply_async(..., retry=False)`). Kombu publishes synchronously, so the service runs it in a thread via `asyncio.to_thread` and the event loop keeps serving other requests.
4. The background Celery worker picks up the job from Redis, locks that notification row, delivers it, and transitions it from `pending` to `sent`.
5. If the publish fails (or a job is lost), the row stays `pending`. A Celery Beat sweep re-publishes it (see [§5](#5-system-resilience--outage-scenarios)).

```
 Client             API (FastAPI)              Postgres               Redis Broker           Celery Worker
   │                      │                       │                        │                       │
   │── POST /assign ─────►│                       │                        │                       │
   │                      │── BEGIN TRANSACTION ─►│                        │                       │
   │                      │   Update task         │                        │                       │
   │                      │   Insert history      │                        │                       │
   │                      │   Insert Notification │                        │                       │
   │                      │   (status='pending')  │                        │                       │
   │                      │── COMMIT ────────────►│                        │                       │
   │                      │                       │                        │                       │
   │                      │── apply_async(notification_id) (thread) ──────►│                       │
   │◄── 200 OK ───────────│                                                │                       │
   │                      │                                                │── BRPOP (claim job) ─►│
   │                      │                                                │                       │── Deliver Notification
   │                      │                                                │                       │   SELECT ... FOR UPDATE
   │                      │                                                │                       │   UPDATE Notification
   │                      │                                                │                       │   SET status='sent'
   │                      │                                                │                       │── ACK job ───────────►
```

---

## 2. Queue, Broker, and Worker Architecture

### Broker & Result Backend Configuration
TaskFlow uses **Redis** as both the message broker and result backend:

- **Broker (`settings.celery_broker_url`)**: `redis://localhost:6379/1` (logical DB 1).
- **Result Backend (`settings.celery_result_backend`)**: `redis://localhost:6379/2` (logical DB 2).
- **Events / Cache**: `redis://localhost:6379/0` (logical DB 0) reserved for Pub/Sub and Streams (#100).

### Worker Reliability Configuration (`app/core/celery_app.py`)
To ensure zero message loss and deterministic task execution:
- **`task_acks_late = True`**: The worker sends an acknowledgment (`ACK`) only *after* the task successfully completes or explicitly exhausts its retries. If a worker process crashes or the container is killed mid-execution, the task remains in Redis and is redelivered.
- **`task_reject_on_worker_lost = True`**: If a worker process dies abruptly (e.g., OOM kill, SIGKILL), Celery re-queues the message rather than discarding it.
- **`worker_prefetch_multiplier = 1`**: Disables aggressive task prefetching. Each worker process takes only one message at a time, ensuring fair distribution and preventing one worker from hoarding tasks during slow execution or retries.
- **`task_serializer = "json"`**: Restricts serialization strictly to JSON, avoiding Python pickle security vulnerabilities.
- **`task_time_limit = 1800` (30 min)** & **`task_soft_time_limit = 1500` (25 min)**: Prevents hanging jobs from locking worker slots indefinitely.
- **`broker_connection_timeout = 1`** & **`broker_transport_options = {"socket_connect_timeout": 1, "socket_timeout": 1}`**: Publishing to a slow or unreachable Redis fails after ~1s instead of the 4s Celery default (and redis-py's unbounded socket connect). Measured locally against an unroutable broker address: 4.07s before, 1.05s after.

### Worker Database Session Isolation (`app/tasks/db.py`)
Celery workers operate asynchronously with their own event loops across worker processes. Sharing connection pools across forks or threads causes `InterfaceError` and event loop collisions.

TaskFlow provides `get_worker_db()`:
- Uses SQLAlchemy `AsyncSession` with `NullPool` (no pooled connection reuse across processes).
- Explicitly disposes the async engine upon exit.
- Provides `run_async(...)` to execute asynchronous coroutines synchronously within Celery worker threads while handling pre-existing event loops safely via thread pools.

---

## 3. Failure Classification: Transient vs Permanent Errors

Not all errors should be retried. Blindly retrying validation errors or non-existent entities wastes worker resources and can hammer downstream services.

```
                                      Notification Task Execution
                                                  │
                                                  ▼
                                       Did an exception occur?
                                        /                 \
                                    Yes /                   \ No
                                       ▼                     ▼
                             Is it transient?          Return Success
                              /            \          (status='sent')
                          Yes/              \ No (Permanent)
                            ▼                ▼
                 retries < max_retries?    Mark DB row 'failed'
                     /          \          Do NOT retry (raise)
                 Yes/            \ No
                   ▼              ▼
           Sleep exponential    Mark DB row 'failed'
           countdown (2**n)     Exhausted retries (raise)
           self.retry()
```

### Transient Failures (Retryable)
Transient errors represent temporary infrastructure blips that are expected to self-heal:
- Database connectivity loss (`OperationalError`, `InterfaceError`, or any `DBAPIError` with `connection_invalidated=True`).
- Socket and network failures (`OSError`, which covers `ConnectionError` and `TimeoutError`).
- Explicit transient failures (`NotificationTransientError`).

Other `DBAPIError` subclasses (`IntegrityError`, `ProgrammingError`, `DataError`) fail the same way on every attempt, so they are **not** retried.

**Retry Policy:**
- **Max Retries**: 3 attempts (`max_retries=3`).
- **Backoff Algorithm**: Exponential backoff with `countdown = 2 ** self.request.retries`:
  - Attempt 1 failure: retry after **1 second** ($2^0$).
  - Attempt 2 failure: retry after **2 seconds** ($2^1$).
  - Attempt 3 failure: retry after **4 seconds** ($2^2$).
- **Terminal State**: If all 3 retries are exhausted, the task updates the pending notification row in PostgreSQL to `status = 'failed'` with the error details and re-raises.

### Permanent Failures (Non-Retryable)
Permanent errors represent deterministic, invariant domain failures:
- Notification row the job was dispatched for does not exist (`NotificationNotFoundError`).
- Target task does not exist (`TaskNotFoundError`).
- Target recipient user does not exist (`RecipientNotFoundError`).
- Task assignee does not match notification recipient (`InvalidAssignmentNotificationError`).
- Base permanent failure (`NotificationPermanentError`).

**Failure Policy:**
- **Retries**: 0 (aborted immediately, `self.retry()` is never called).
- **Audit**: The task immediately updates its own notification row (only if still `pending`) to `status = 'failed'`, records the exact error in the JSON payload, logs an `ERROR` level message, and terminates.

### Unexpected Errors
Any other exception (a `KeyError`, `ValueError`, or a bug) is neither retried nor left silent: the task logs it with a traceback, marks the row `failed` with `"<ExceptionType>: <message>"` in the payload, and re-raises so it shows as a failure in Flower.

---

## 4. Idempotency Guarantees

In distributed systems with `task_acks_late=True` and automatic retries, **at-least-once delivery** means a task may execute more than once (e.g. worker network cuts out after completing work but before the ACK reaches Redis).

### Deduplication Strategy
The **notification row is the idempotency key**. `assign_task` flushes the `pending` row inside the assignment transaction to get its id, and the job receives only `notification_id`. The task implementation in [`app/tasks/notification_tasks.py`](../../app/tasks/notification_tasks.py):

1. **Lock the row**: `SELECT ... FROM notification WHERE id = :notification_id FOR UPDATE`. A redelivered (`acks_late`) or concurrently running copy of the same job blocks here until the first copy commits.
2. **Short-Circuit unless pending**: If the row is already `sent` (or `failed`/`cancelled`), the task logs an idempotent skip and returns immediately:
   ```json
   {
     "status": "already_sent",
     "notification_id": 142,
     "task_id": 10,
     "recipient_id": 5,
     "idempotent": true
   }
   ```
3. **Validate and Deliver**: Check the task and recipient exist and the task is still assigned to the recipient, then update the row in place to `status = "sent"`, enriching its payload (`dispatched: true`, `task_title`).

### Why not key on `(task_id, recipient_id)`?
An earlier version looked up all `TASK_ASSIGNED` rows for the task and recipient and skipped delivery if *any* was `sent`. For a task reassigned **A → B → A**, the second assignment to A found A's old `sent` row and returned `already_sent`, leaving the new `pending` row undelivered. Keying on the row id means each assignment gets exactly one delivery. `tests/integration/services/test_celery_assignment_flow.py::test_reassignment_back_to_earlier_assignee_delivers_new_notification` covers this case.

---

## 5. System Resilience & Outage Scenarios

| Failure Scenario | Behavior & Guarantee |
| :--- | :--- |
| **Celery Worker is Down** | The API successfully commits the task assignment to PostgreSQL and pushes the job into Redis queue `celery`. The job sits safely in Redis memory. When a worker process starts, it immediately pops and processes all queued notifications without data loss. |
| **Worker Crashes Mid-Task** | Because `task_acks_late=True` and `task_reject_on_worker_lost=True`, Redis holds the message until acknowledged. A surviving or restarted worker reclaims the message. Thanks to idempotency, partial work is reconciled without duplicates. |
| **Redis Broker is Down** | The database transaction for task assignment has already committed. The publish runs in a thread with `retry=False` and 1s broker timeouts, so the request is delayed by about a second at most and the event loop is never blocked. The error is logged as a warning and the API returns HTTP 200. The notification stays `pending` in PostgreSQL until the outbox sweep re-publishes it. |
| **Job Lost (publish failed, or message dropped)** | `requeue_stale_assignment_notifications` runs on Celery Beat every `notification_requeue_interval_seconds` (default 300s). It selects up to `notification_requeue_batch_size` (default 100) `TASK_ASSIGNED` rows still `pending` after `notification_requeue_after_minutes` (default 5) and re-publishes each one by `notification_id`. Re-publishing a row whose job is still in flight is safe because delivery locks the row and skips anything not `pending`. Rows marked `failed` are not re-sent automatically. |
| **Database Outage During Worker Run** | The worker raises `OperationalError`, which is caught as a transient failure. Celery retries with exponential backoff up to 3 times while waiting for the database connection to recover. |

---

## 6. Verification & Commands

### Running the End-to-End Demo
To verify all 7 scenarios (dispatch, delivery, idempotency, retry backoff, permanent failure, worker-down buffering, A → B → A reassignment):

```bash
make celery-demo
```
*(Or directly: `uv run python -m scripts.demo_celery_jobs`)*

### Starting the Worker and Beat Locally
```bash
make celery-worker
make celery-beat   # runs the stale-pending outbox sweep
```

### Inspecting Redis Broker Shell
```bash
make redis-cli
# Inside redis-cli:
LLEN celery
LRANGE celery 0 -1
```

### Running Test Suites
```bash
# Unit tests (exception hierarchy, backoff calculation, retry limits, retry classification)
uv run pytest tests/unit/test_celery_notification_tasks.py

# Integration tests (transaction commit, broker offline resilience, DB delivery, idempotency,
# A -> B -> A reassignment, outbox sweep selection)
uv run pytest tests/integration/services/test_celery_assignment_flow.py
```
