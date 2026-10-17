# Demo 05 — Celery Beat Periodic Jobs & Flower Monitoring

Issue **#102**. Scheduled tasks (such as due-task reminders) must run automatically on a recurring schedule without user request intervention.
This demo proves four core behaviors:
1. **Accurate Due-Date Filtering**: Reminders are generated exclusively for incomplete assigned tasks due within the threshold window.
2. **Concurrency Overlap Protection**: When a prior sweep is running or taking longer than expected, overlapping scheduler runs are safely skipped using a Redis distributed lock.
3. **Idempotent Deduplication**: Running the scheduler repeatedly (e.g. every minute) does NOT spam assignees with duplicate reminders.
4. **Flower Monitoring**: Celery Flower provides real-time web observability into worker pools, queues, and task states.

Architecture details: [`docs/session-05/celery-beat.md`](../../../docs/session-05/celery-beat.md) and [`docs/session-05/flower-monitoring.md`](../../../docs/session-05/flower-monitoring.md).

---

## Loom Video
- Loom Video: `[Link to be added after recording demo walkthrough]`

---

## Objective
Prove that:
- Celery Beat periodic scheduler sweeps active tasks and sends reminders only to assignees with tasks due soon or overdue.
- Overlapping runs are rejected cleanly via Redis distributed lock (`SET ... NX EX`).
- Consecutive scheduler runs deduplicate reminders within a 24-hour window.
- Flower dashboard tracks worker heartbeats, task throughput, and Celery Beat schedules.

---

## Scenario
A team lead assigns four tasks with varying due dates and completion states:
1. **Task 1**: Due **today**, `in_progress`, assigned to developer -> **Must receive reminder**.
2. **Task 2**: Due in **30 days**, `todo`, assigned to developer -> **Must NOT receive reminder**.
3. **Task 3**: Due **today**, `done` (completed), assigned to developer -> **Must NOT receive reminder**.
4. **Task 4**: Due **today**, `todo`, unassigned (`assignee_id=None`) -> **Must NOT receive reminder**.

While the scheduled job executes, we simulate a long-running process that holds the lock, triggering an overlapping scheduler tick to verify that it skips execution without corrupting state.

---

## Commands / Steps Used

### 1. Run Automated Demonstration
```bash
make beat-demo
```
*(Runs `scripts/demo_celery_beat.py` validating due-date filtering, Redis lock overlap rejection, consecutive deduplication, and schedule inspection).*

### 2. Start Celery Beat & Worker in Docker
```bash
# Start Postgres, Redis, Celery Worker, Celery Beat, and Flower
docker compose up -d db redis celery-worker celery-beat flower

# Verify all services are running and healthy
docker compose ps
```

### 3. Open Flower Monitoring Dashboard
```bash
# Open Flower web UI in browser
open http://localhost:5555
```

### 4. Run Pytest Suite
```bash
# Unit and integration test coverage for Beat and Reminder tasks
uv run pytest tests/unit/test_celery_beat_reminders.py tests/integration/services/test_celery_beat_flow.py -v
```

---

## Expected vs Actual Findings

| Criterion | Expected Behavior | Actual Finding | Status |
| :--- | :--- | :--- | :---: |
| **Due-Date Filtering** | Only Task 1 (due today, incomplete, assigned) receives a reminder. Tasks 2, 3, and 4 are ignored. | `reminders_created: 1`, `reminded_task_ids: [13]`. Only Task 1 received a reminder. | **PASS** |
| **Overlap Protection** | When Redis lock is held, overlapping run skips execution immediately. | Returned `status: skipped, reason: overlapping_run, reminders_created: 0`. | **PASS** |
| **Idempotency** | Subsequent sweep detects existing 24h reminder and generates 0 duplicates. | Returned `reminders_created: 0, reminders_skipped: 1`. Total DB rows = 1. | **PASS** |
| **Flower Dashboard** | Web dashboard at `http://localhost:5555` displays online workers and schedules. | Flower service starts healthy and reports worker pools and task statistics. | **PASS** |

---

## Evidence

### Automated Run Output (`make beat-demo`)

```text
===========================================================================
  TaskFlow — Session 05 Demo: Celery Beat Due-Task Reminders & Overlap Prevention
===========================================================================

[OK] Connected to Redis Broker at redis://localhost:6379/0
[OK] Connected to Postgres Database: /taskflow

>> Setting up Test Tasks and Users for Due-Date Scenarios
  • Task 1 (ID=13): Due TODAY, in_progress, assigned to 4
  • Task 2: Due +30 days, todo, assigned
  • Task 3: Due TODAY, done, assigned
  • Task 4: Due TODAY, todo, unassigned

>> Step 1: Execute Celery Beat Due-Task Reminder Sweep
  • Sweep completed in 9.78 ms
  • Result metrics: {'status': 'success', 'tasks_checked': 1, 'reminders_created': 1, 'reminders_skipped': 0, 'reminded_task_ids': [13]}
  • Verified Notification in DB: ID=7, Type=TASK_DUE_REMINDER, Status=sent
  • Stored Payload: {'status': 'in_progress', 'task_id': 13, 'due_date': '2026-10-17', 'priority': 'high', 'is_overdue': False, 'task_title': 'Beat Test Task #1 - Due Today'}
  [PASS] Exactly 1 reminder generated for the qualified due task.

>> Step 2: Simulate Overlapping Scheduler Run (Redis Lock Overlap Check)
  Acquiring Redis lock artificially to simulate another long-running sweep...
  • Active Lock Key 'taskflow:locks:send_due_task_reminders' held with token 90ee5ecf...
  Attempting concurrent sweep while lock is active...
Another due-task reminder sweep is currently in progress. Skipping overlapping run.
  • Concurrent Sweep Response: {'status': 'skipped', 'reason': 'overlapping_run', 'reminders_created': 0, 'reminders_skipped': 0}
  [PASS] Overlapping run was rejected immediately without duplicate work.
  • Released simulated lock successfully.

>> Step 3: Consecutive Sweep Deduplication Check (No Duplicate Reminders)
  Running sweep again with lock released...
  • Second Sweep Response: {'status': 'success', 'tasks_checked': 1, 'reminders_created': 0, 'reminders_skipped': 1, 'reminded_task_ids': []}
  • Total DB notifications for task 13: 1
  [PASS] Zero duplicate notifications created on subsequent sweep.

>> Step 4: Inspect Celery Beat Schedule & Flower Observability
  • Registered Celery Beat Periodic Jobs:
    - 'send-due-task-reminders-periodic': task=app.tasks.reminder_tasks.send_due_task_reminders, schedule=60.0s

  • Flower Observability Service:
    - URL: http://localhost:5555
    - Capabilities: Worker heartbeats, active tasks, retries, periodic schedules

===========================================================================
  TaskFlow — Session 05 Demo: All Celery Beat & Due Reminder Behaviors Verified Successfully!
===========================================================================
```

### Pytest Suite Output

```text
$ uv run pytest tests/unit/test_celery_beat_reminders.py tests/integration/services/test_celery_beat_flow.py -v
============================= test session starts ==============================
collected 12 items

tests/unit/test_celery_beat_reminders.py::test_acquire_and_release_redis_lock_success PASSED [  8%]
tests/unit/test_celery_beat_reminders.py::test_acquire_redis_lock_already_held PASSED [ 16%]
tests/unit/test_celery_beat_reminders.py::test_release_redis_lock_mismatched_token PASSED [ 25%]
tests/unit/test_celery_beat_reminders.py::test_distributed_lock_context_manager_acquires_and_releases PASSED [ 33%]
tests/unit/test_celery_beat_reminders.py::test_process_due_task_reminders_skips_when_lock_held PASSED [ 41%]
tests/unit/test_celery_beat_reminders.py::test_beat_schedule_configuration PASSED [ 50%]
tests/unit/test_celery_beat_reminders.py::test_celery_task_registration PASSED [ 58%]
tests/unit/test_celery_beat_reminders.py::test_send_due_task_reminders_task_invokes_process PASSED [ 66%]
tests/integration/services/test_celery_beat_flow.py::test_due_task_reminders_filters_and_delivers PASSED [ 75%]
tests/integration/services/test_celery_beat_flow.py::test_due_task_reminders_idempotent_no_duplicates PASSED [ 83%]
tests/integration/services/test_celery_beat_flow.py::test_completed_tasks_do_not_receive_reminders PASSED [ 91%]
tests/integration/services/test_celery_beat_flow.py::test_overlapping_sweep_skips_execution PASSED [100%]

============================== 12 passed in 0.85s ==============================
```

---

## What We Learned

1. **Distributed Locks Require Safe Release Semantics**:
   Using `redis.set(..., nx=True, ex=timeout)` is only half the solution. Releasing with a naive `DEL` risks clearing another worker's lock if execution exceeded the timeout. The atomic Lua script ensures the release only succeeds if the caller's unique UUID token matches.
2. **Frequency vs Deduplication Decoupling**:
   Beat can safely run at high frequency (e.g. every minute to detect newly due tasks) while the application maintains a 24-hour reminder deduplication window, ensuring high responsiveness without notification fatigue.
3. **Observability via Flower**:
   Flower provides instantaneous visual confirmation that workers are alive, queues are healthy, and periodic schedules are registered, reducing dependence on raw stdout logs.

---

## Open Questions

- Should assignees be permitted to snooze reminders or configure notification preferences? *(Currently out of scope per Issue #102 requirements).*
