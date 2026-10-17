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
3. Immediately **after commit**, the API enqueues a background task via Celery (`send_task_assignment_notification.delay(...)`) and responds to the client immediately (< 5ms dispatch).
4. The background Celery worker picks up the job from Redis, delivers the notification, and transitions the row from `pending` to `sent`.

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
   │                      │── .delay(task, user) ─────────────────────────►│                       │
   │◄── 200 OK ───────────│                                                │                       │
   │   (sub-millisecond)  │                                                │── BRPOP (claim job) ─►│
   │                      │                                                │                       │── Deliver Notification
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
- Database connectivity loss (`OperationalError`, `DBAPIError`).
- Socket and network timeouts (`ConnectionError`, `TimeoutError`, `OSError`).
- Explicit transient failures (`NotificationTransientError`).

**Retry Policy:**
- **Max Retries**: 3 attempts (`max_retries=3`).
- **Backoff Algorithm**: Exponential backoff with `countdown = 2 ** self.request.retries`:
  - Attempt 1 failure: retry after **1 second** ($2^0$).
  - Attempt 2 failure: retry after **2 seconds** ($2^1$).
  - Attempt 3 failure: retry after **4 seconds** ($2^2$).
- **Terminal State**: If all 3 retries are exhausted, the task updates the pending notification row in PostgreSQL to `status = 'failed'` with the error details and re-raises.

### Permanent Failures (Non-Retryable)
Permanent errors represent deterministic, invariant domain failures:
- Target task does not exist (`TaskNotFoundError`).
- Target recipient user does not exist (`RecipientNotFoundError`).
- Task assignee does not match notification recipient (`InvalidAssignmentNotificationError`).
- Base permanent failure (`NotificationPermanentError`).

**Failure Policy:**
- **Retries**: 0 (aborted immediately, `self.retry()` is never called).
- **Audit**: The task immediately updates any pending notification row to `status = 'failed'`, records the exact error in the JSON payload, logs an `ERROR` level message, and terminates.

---

## 4. Idempotency Guarantees

In distributed systems with `task_acks_late=True` and automatic retries, **at-least-once delivery** means a task may execute more than once (e.g. worker network cuts out after completing work but before the ACK reaches Redis).

### Deduplication Strategy
The task implementation in [`app/tasks/notification_tasks.py`](../../app/tasks/notification_tasks.py) enforces idempotency at the database layer:

1. **Query Existing Notifications**: Before taking action, query the `notification` table for matching `(task_id, recipient_id, type="TASK_ASSIGNED")`.
2. **Short-Circuit on Delivered**: If an existing notification has `status == "sent"`, the task logs an idempotent skip and returns immediately:
   ```json
   {
     "status": "already_sent",
     "notification_id": 142,
     "task_id": 10,
     "recipient_id": 5,
     "idempotent": true
   }
   ```
   No duplicate database rows are created, and no duplicate notifications are sent to the user.
3. **Transition Pending to Sent**: If a notification exists with `status == "pending"`, it is updated in-place to `status = "sent"`, enriching its payload with delivery metadata (`dispatched: true`, `task_title`, `timestamp`).
4. **Fallback Creation**: If no notification record existed, a new row is created with `status = "sent"`.

---

## 5. System Resilience & Outage Scenarios

| Failure Scenario | Behavior & Guarantee |
| :--- | :--- |
| **Celery Worker is Down** | The API successfully commits the task assignment to PostgreSQL and pushes the job into Redis queue `celery`. The job sits safely in Redis memory. When a worker process starts, it immediately pops and processes all queued notifications without data loss. |
| **Worker Crashes Mid-Task** | Because `task_acks_late=True` and `task_reject_on_worker_lost=True`, Redis holds the message until acknowledged. A surviving or restarted worker reclaims the message. Thanks to idempotency, partial work is reconciled without duplicates. |
| **Redis Broker is Down** | The database transaction for task assignment has already committed. The API's `.delay()` call catches the broker connection error, logs a warning, and returns HTTP 200 to the user. The assignment succeeds. The notification remains in `pending` status in PostgreSQL, serving as an outbox record that can be re-dispatched. |
| **Database Outage During Worker Run** | The worker raises `OperationalError`, which is caught as a transient failure. Celery retries with exponential backoff up to 3 times while waiting for the database connection to recover. |

---

## 6. Verification & Commands

### Running the End-to-End Demo
To verify all 6 scenarios (latency, delivery, idempotency, retry backoff, permanent failure, worker-down buffering):

```bash
make celery-demo
```
*(Or directly: `uv run python -m scripts.demo_celery_jobs`)*

### Starting the Worker Locally
```bash
make celery-worker
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
# Unit tests (exception hierarchy, backoff calculation, retry limits)
uv run pytest tests/unit/test_celery_notification_tasks.py

# Integration tests (transaction commit, broker offline resilience, DB delivery, idempotency)
uv run pytest tests/integration/services/test_celery_assignment_flow.py
```
