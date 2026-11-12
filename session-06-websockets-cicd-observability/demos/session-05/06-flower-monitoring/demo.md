# Demo 06 — Flower Monitoring

Issue **#102**, used as the "Flower shows job behavior" step of the end-to-end flow (#104).
Setup and access rules: [`docs/session-05/flower-monitoring.md`](../../../docs/session-05/flower-monitoring.md).

## Loom Video
- Loom Video: `[Link to be added after recording demo walkthrough]`

## Objective
Show that Flower answers the operational questions about the background jobs: is a worker
online, which jobs ran, did they succeed, fail or retry, and is Beat ticking. Also show
that it is not reachable without a login.

## Scenario
An operator is checking that a task assignment's notification went out and that the
reminder sweep is running, without reading container logs.

## Commands / Steps Used
```bash
make docker-up      # FLOWER_BASIC_AUTH=user:password must be set in .env
make flow-demo      # produces a delivery job and waits for a reminder sweep

# The login lives in .env, which the shell does not load. Take the first user:password
# (FLOWER_BASIC_AUTH may list several, comma-separated).
FLOWER_LOGIN=$(grep '^FLOWER_BASIC_AUTH=' .env | cut -d= -f2- | cut -d, -f1)

# Login required
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5555/api/workers   # 401
curl -s -u "$FLOWER_LOGIN" 'http://127.0.0.1:5555/api/workers?refresh=true'

# Job history by name and state
curl -s -u "$FLOWER_LOGIN" 'http://127.0.0.1:5555/api/tasks?limit=200'
curl -s -u "$FLOWER_LOGIN" 'http://127.0.0.1:5555/api/tasks?state=FAILURE&limit=5'

# A job that fails permanently (no such notification), to see a failure in Flower
uv run python -c "from app.tasks.notification_tasks import send_task_assignment_notification as t; \
print(t.apply_async(kwargs={'notification_id': 999999}).id)"
```
In the UI: **Workers** for the pool and registered tasks, **Tasks** for the history (filter
by name or state, open a task for its args, result or traceback), and **Broker** for the
queue depth.

## Expected vs Actual Findings

| Check | Expected | Actual | Status |
| :--- | :--- | :--- | :---: |
| Access | No login, no data | `401` without credentials | **PASS** |
| Worker | One worker online with all three jobs registered | `celery@6da12e3ce67d`, pool of 8, 3 registered tasks | **PASS** |
| Delivery job | The flow's `send_task_assignment_notification` is listed as succeeded | `SUCCESS`, kwargs `{'notification_id': 54}` | **PASS** |
| Beat | `send_due_task_reminders` appears once per minute | One `SUCCESS` per 60s tick; result lists `reminded_task_ids` | **PASS** |
| Failure | A permanent failure shows as `FAILURE` with its exception and is not retried | `FAILURE`, `NotificationNotFoundError(...)`, no retries | **PASS** |

## Evidence

### Workers (`/api/workers?refresh=true`, summarised)
```text
celery@6da12e3ce67d pool: 8 registered: ['app.tasks.notification_tasks.requeue_stale_assignment_notifications',
  'app.tasks.notification_tasks.send_task_assignment_notification', 'app.tasks.reminder_tasks.send_due_task_reminders']
```

### Job history after `make flow-demo` (`/api/tasks`, counted by name and state)
```text
2 app.tasks.notification_tasks.send_task_assignment_notification SUCCESS
4 app.tasks.reminder_tasks.send_due_task_reminders SUCCESS
```

### Reminder sweep result, as Flower shows it
```text
http://127.0.0.1:5555/task/54f6b5f4-f7d7-4863-acb5-5e715a821931
result={'status': 'success', 'tasks_checked': 44, 'reminders_created': 1, 'reminders_skipped': 43,
        'reminders_failed': 0, 'reminded_task_ids': [215]}
```

### Permanent failure (`/api/tasks?state=FAILURE`)
```text
008479de-7bbc-4d62-a101-a181c6859519 FAILURE {'notification_id': 999999}
NotificationNotFoundError('Notification with id 999999 not found.')
```

### Beat ticks (`make docker-logs s=celery-beat`)
```text
[2026-10-25 11:16:36,226: INFO/MainProcess] [-] Scheduler: Sending due task send-due-task-reminders-periodic (...)
[2026-10-25 11:17:36,226: INFO/MainProcess] [-] Scheduler: Sending due task send-due-task-reminders-periodic (...)
[2026-10-25 11:18:36,362: INFO/MainProcess] [-] Scheduler: Sending due task send-due-task-reminders-periodic (...)
```

## What We Learned
- Flower answers "did the job run and how did it end". What the job did lives elsewhere: the
  delivery is in the `notification` table, and the request that caused it is in the logs
  under the same request id.
- Job history is kept in Flower's memory and starts over when Flower restarts. It is a
  live view, not an audit trail.
- Flower can revoke tasks and shows job arguments, so it stays on loopback behind basic auth.

## Open Questions
- Which of these checks should become alerts (no worker online, failure rate, queue depth,
  no reminder sweep in 5 minutes) instead of something a person looks at?
- Should Flower run with `--persistent` so job history survives a restart?
