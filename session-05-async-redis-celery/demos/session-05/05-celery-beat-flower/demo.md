# Demo 05 — Celery Beat Periodic Jobs & Flower Monitoring

> Note: This document is identical to [`demos/session-05/05-celery-beat/demo.md`](../05-celery-beat/demo.md), provided here to match the path referenced in GitHub Issue #102.

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

---

## Commands / Steps Used

```bash
# 1. Run Automated Demonstration
make beat-demo

# 2. Start Celery Beat & Worker in Docker
docker compose up -d db redis celery-worker celery-beat flower

# 3. Open Flower Monitoring Dashboard
open http://localhost:5555

# 4. Run Pytest Suite
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
