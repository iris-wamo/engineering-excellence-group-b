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
- Beat maintains its own schedule state in a schedule file (e.g. `/tmp/celerybeat-schedule` in Docker or local disk), tracking when each task was last enqueued.

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
        "send-due-task-reminders-periodic": {
            "task": "app.tasks.reminder_tasks.send_due_task_reminders",
            "schedule": settings.celery_beat_schedule_interval_seconds,  # default: 60.0s
        },
    },
)
```

In development and testing, `celery_beat_schedule_interval_seconds` is set to 60 seconds (or overridden via environment variables). In production, this can be customized to a crontab expression (e.g. every morning at 09:00 UTC).

---

## 3. Concurrency & Overlap Prevention via Redis Distributed Locks

### The Overlap Hazard
When a periodic task runs on a short interval (e.g., every 60 seconds) or when database queries take longer than expected under load, **Beat can fire a second task before the previous execution has finished**.
Without concurrency control:
1. Two workers would query the database concurrently.
2. Both would see the same candidate tasks.
3. Both would attempt to create notifications, leading to race conditions and duplicate reminders.

### Distributed Lock Implementation (`app/tasks/locks.py`)
To prevent overlapping runs across multiple Celery workers:
1. The worker attempts to acquire an exclusive lock in Redis:
   ```python
   acquired = await redis_client.set(lock_key, token, nx=True, ex=300)
   ```
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
   *Why Lua?* If the task took longer than `ex=300` seconds and the lock expired, another worker might have acquired it. A simple `DEL` command would inadvertently release the *new* worker's lock. The Lua script guarantees that only the process holding the matching UUID token can delete the key.

---

## 4. Due-Date Filtering & Deduplication

### Candidate Selection Rules
A task qualifies for a reminder only if all four conditions are met:
1. `Task.due_date IS NOT NULL`
2. `Task.assignee_id IS NOT NULL` (unassigned tasks have no recipient)
3. `Task.status != TaskStatus.done` (completed tasks do not need reminders)
4. `Task.due_date <= today + timedelta(days=threshold_days)` (tasks due today, soon, or overdue)

### Entity-Level Deduplication Window
Even without concurrent overlap, periodic jobs tick repeatedly (e.g. every minute or hour). To avoid spamming assignees with dozens of reminders for the same deliverable:
- Before inserting a `Notification` with `type="TASK_DUE_REMINDER"`, the worker queries existing notifications:
  ```python
  cutoff = datetime.now(UTC) - timedelta(hours=dedup_window_hours)  # default: 24h
  existing = (await db.scalars(
      select(Notification).where(
          Notification.task_id == task.id,
          Notification.recipient_id == task.assignee_id,
          Notification.type == "TASK_DUE_REMINDER",
          Notification.created_at >= cutoff,
      )
  )).first()
  ```
- If an existing reminder exists within the last 24 hours, the task is skipped and logged as `reminders_skipped += 1`.
- This ensures **at most one reminder per 24 hours per task** regardless of how frequently Celery Beat runs.

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
