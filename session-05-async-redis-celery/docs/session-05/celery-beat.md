# Celery Beat Periodic Jobs: Due-Task Reminders & Overlap Prevention

Issue **#102**. In TaskFlow, notifications for task assignments happen asynchronously post-commit (#101).
However, reminders for tasks approaching their due date represent **scheduled work**, not user-request work.
This document details the periodic scheduler architecture, overlap prevention using Redis distributed locks,
and idempotency strategies for due-task reminders.

---

## 1. Scheduled Recurring Work: Why Celery Beat?

### The Problem with On-Demand Reminders
- Unlike assignment notifications that are triggered by an explicit HTTP request (`POST /assign`), due-date reminders are time-driven.
- Without a periodic scheduler, an API endpoint would need to be polled by external cron, coupling infrastructure maintenance with user traffic.

### The Solution: Celery Beat
- **Celery Beat** is a scheduler process that reads a configured periodic task schedule and posts execution messages to the Celery broker (Redis list `celery`) at specified intervals.
- The Celery worker processes the messages asynchronously just like any other task.
- Beat maintains its own schedule state in a schedule file (e.g. `/tmp/celerybeat-schedule` in Docker or local disk), tracking when each task was last enqueued. In Docker that file is container-local and is **not** persisted across container recreation. Both schedule entries are fixed intervals, so a fresh Beat just runs them on its first tick.

```
┌──────────────────┐
│   Celery Beat    │ ── (every 60s) ──► ┌──────────────┐ ──► ┌──────────────────┐
│ Periodic Process │                    │ Redis Broker │     │  Celery Worker   │
└──────────────────┘                    │ (DB 1 Queue) │     │ (nullpool async) │
                                        └──────────────┘     └─────────┬────────┘
                                                                       │
                                             ┌─────────────────────────┴────────────────────────┐
                                             ▼                                                  ▼
                                ┌─────────────────────────┐                        ┌────────────────────────┐
                                │   PostgreSQL (RDS/DB)   │                        │   Redis (Locks DB 0)   │
                                │ • Filter due tasks      │                        │ • Acquire Lock (NX EX) │
                                │ • Insert Notification   │                        │ • Atomic Lua Release   │
                                └─────────────────────────┘                        └────────────────────────┘
```

---

## 2. Schedule Configuration (`app/core/celery_app.py`)

The schedule is registered directly inside the Celery application configuration:

```python
celery_app.conf.update(
    ...,
    beat_schedule={
        "requeue-stale-assignment-notifications": {
            "task": "app.tasks.notification_tasks.requeue_stale_assignment_notifications",
            "schedule": settings.notification_requeue_interval_seconds,  # default: 300.0s
        },
        "send-due-task-reminders-periodic": {
            "task": "app.tasks.reminder_tasks.send_due_task_reminders",
            "schedule": settings.due_reminder_interval_seconds,  # default: 60.0s
        },
    },
)
```

The same Beat process also runs the assignment-notification outbox sweep from #101, which re-publishes `TASK_ASSIGNED` rows left `pending` (see [`celery-jobs.md`](celery-jobs.md) §5).

In development and testing, `due_reminder_interval_seconds` (`DUE_REMINDER_INTERVAL_SECONDS`) is 60 seconds. The lock TTL is derived from it (below); the dedup window (`DUE_REMINDER_DEDUP_HOURS`, 24h) is a separate setting because it is how often a person may be reminded, not how often the sweep checks. In production, this can be customized to a crontab expression (e.g. every morning at 09:00 UTC).

---

## 3. Concurrency & Overlap Prevention via Redis Distributed Locks

### The Overlap Hazard
When a periodic task runs on a short interval (e.g., every 60 seconds) or when database queries take longer than expected under load, **Beat can fire a second task before the previous execution has finished**.
Without concurrency control:
1. Two workers would query the database concurrently.
2. Both would see the same candidate tasks.
3. Both would attempt to create notifications, leading to race conditions and duplicate reminders.

### Distributed Lock Implementation (`taskflow_shared.locks`)
The lock is domain-free, so it lives in the shared package (`packages/taskflow_shared/taskflow_shared/locks/redis_lock.py`). The sweep passes it a client from `app.db.redis.create_redis_client()`, so lock commands get the same 2s connect and read timeouts as every other Redis call instead of waiting forever on a hung server, and closes that client afterwards.

To prevent overlapping runs across multiple Celery workers:
1. The worker attempts to acquire an exclusive lock in Redis:
   ```python
   acquired = await redis_client.set(lock_key, token, nx=True, ex=settings.due_reminder_lock_ttl_seconds)
   ```
   The TTL is five sweep intervals, at least 60s (300s at the 60s default). While the sweep runs, a background task renews it every third of the TTL with a token-checked Lua `EXPIRE`, so a sweep slower than the TTL keeps its lock and the next Beat tick still skips. The TTL only matters if the worker dies mid-sweep: the lock then expires and the next tick takes over. If a renewal finds the lock gone, it logs a warning.
2. If `token is None` (the lock is already held by an ongoing run):
   The task logs a warning and exits cleanly without error or duplicate queries:
   ```json
   {"status": "skipped", "reason": "overlapping_run", "reminders_created": 0}
   ```
3. When the execution finishes, the lock is released **atomically** via a Lua script:
   ```lua
   if redis.call("get", KEYS[1]) == ARGV[1] then
       return redis.call("del", KEYS[1])
   else
       return 0
   end
   ```
   *Why Lua?* If the holder died and its lock expired, another worker might have acquired it. A simple `DEL` command would inadvertently release the *new* worker's lock. The Lua script guarantees that only the process holding the matching UUID token can delete the key.

---

## 4. Due-Date Filtering & Deduplication

### Candidate Selection Rules
A task qualifies for a reminder only if all four conditions are met:
1. `Task.due_date IS NOT NULL`
2. `Task.assignee_id IS NOT NULL` (unassigned tasks have no recipient)
3. `Task.status != TaskStatus.done` (completed tasks do not need reminders)
4. `Task.due_date <= today + timedelta(days=threshold_days)` (tasks due today, soon, or overdue)

`today` is the **UTC** calendar day (`datetime.now(UTC).date()`), not the worker's local date, so a container running in another timezone does not shift reminders by a day.

### Entity-Level Deduplication Window
Even without concurrent overlap, periodic jobs tick repeatedly (e.g. every minute or hour). To avoid spamming assignees with dozens of reminders for the same deliverable:
- Before inserting any `Notification` with `type="TASK_DUE_REMINDER"`, the worker fetches the `(task_id, recipient_id, due_date)` reminders already sent in the window, in one query per batch of candidate tasks (no N+1):
  ```python
  cutoff = datetime.now(UTC) - timedelta(hours=dedup_window_hours)  # default: 24h
  already_reminded = {
      (task_id, recipient_id, due_date)
      for task_id, recipient_id, due_date in await db.execute(
          select(
              Notification.task_id,
              Notification.recipient_id,
              Notification.payload["due_date"].astext,
          ).where(
              Notification.task_id.in_(batch_task_ids),
              Notification.type == "TASK_DUE_REMINDER",
              Notification.created_at >= cutoff,
          )
      )
  }
  ```
- If `(task.id, task.assignee_id, task.due_date)` is in that set, the task is skipped and counted in `reminders_skipped`.
- This ensures **at most one reminder per 24 hours per task, assignee and due date** regardless of how frequently Celery Beat runs. A task reassigned within the window still reminds its new assignee, and a task whose due date moves is reminded again for the new date.

### Batches and Row Isolation
Candidate tasks are read `DUE_REMINDER_BATCH_SIZE` (500) at a time with keyset pagination on `(due_date, id)`, and each batch is committed on its own, so a large backlog never sits in memory or in one long transaction. Each reminder is inserted in its own savepoint: a row that fails (for example, its task was deleted meanwhile) is logged, counted in `reminders_failed` and skipped, and the rest of the batch is kept.

### Failure Handling
`send_due_task_reminders` does not retry (`max_retries=0`). Any failure is logged with a traceback and raised so Flower shows it, and Beat runs the sweep again on its next tick (60s by default). The dedup window makes that re-run safe.

---

## 5. Running and Validating Locally

```bash
# 1. Start Postgres, Redis, and Celery Worker
docker compose up -d db redis celery-worker

# 2. Run Celery Beat locally
make celery-beat

# 3. Run automated demo validating matching, overlap rejection, and deduplication
make beat-demo

# 4. Run test suite
uv run pytest tests/unit/test_celery_beat_reminders.py tests/integration/services/test_celery_beat_flow.py -v
```
