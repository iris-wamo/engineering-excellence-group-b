# Demo 07 — End-to-End Notification and Reminder Flow

Issue **#104**. One task change goes through every Session 05 component: the API responds
quickly, Redis handles the cache and the events, Celery runs the side effects, Beat
schedules the reminders, and Flower shows the jobs.

Architecture, failure cases and tradeoffs: [`docs/session-05/end-to-end-flow.md`](../../../docs/session-05/end-to-end-flow.md).

## Loom Video
- Loom Video: `[Link to be added after recording demo walkthrough]`

## Objective
Show, on the running Docker stack, that a single assignment:
- is answered by the API in tens of milliseconds, without waiting on any side effect;
- invalidates the cached task summary;
- lands on the Redis Stream (and Pub/Sub) as a `task.assigned` event;
- is delivered by the Celery worker from the notification outbox;
- is picked up by Beat's due-task sweep, which reminds the assignee;
- is visible in Flower, and in the api and worker logs under one request id.

## Scenario
Maya (manager) and Dana (developer) share a project. Maya creates a task due today and
assigns it to Dana, then Dana starts it. Nobody calls the worker or Beat by hand.

## Commands / Steps Used

### 1. Start the full stack (terminal 1)
```bash
# FLOWER_BASIC_AUTH=user:password must be set in .env; Compose refuses to start without it
make docker-build
make docker-up
docker compose ps    # api, db, mongo, redis, celery-worker, celery-beat, flower: all running
```

### 2. Watch each component (one terminal each)
```bash
make docker-logs s=api                 # cache INVALIDATED / HIT / MISS, Published task.* events
make events-streams NAME=flow-1        # the Streams consumer applying task.* events
docker compose logs -f celery-worker celery-beat   # job delivery and the Beat ticks
open http://127.0.0.1:5555             # Flower, log in with FLOWER_BASIC_AUTH
```

### 3. Run the scripted flow (terminal 1)
```bash
make flow-demo
```
The script signs up both users, inserts the project and roles, creates the task through the
API, and then checks each step from the outside (Redis keys, the stream, the `notification`
table, Flower's API). The reminder step waits for the next Beat tick, up to 90s. It exits
non-zero if any check fails.

### 4. Follow one request through the logs
```bash
# Use the request id the script prints for the assignment
docker compose logs api celery-worker --no-log-prefix | grep <request-id>
```

### 5. Manual version (for the recording)
The same flow with curl, set up as in steps 3–4 of
[Demo 03](../03-redis-pubsub-streams/demo.md#3-create-a-manager-a-developer-a-project-and-a-task-terminal-1)
(`$API`, `$H`, `$MT`, `$DT`, `$PID`, `$DID`):
```bash
TID=$(curl -s -X POST $API/tasks -H "$H" -H "Authorization: Bearer $MT" \
  -d "{\"title\": \"Flow demo\", \"project_id\": $PID, \"due_date\": \"$(date -u +%F)\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')

curl -s $API/tasks/summary > /dev/null && curl -s $API/tasks/summary > /dev/null   # MISS, then HIT
curl -si -X POST $API/tasks/$TID/assign -H "$H" -H "Authorization: Bearer $MT" \
  -d "{\"assignee_id\": $DID}" | grep -i x-request-id
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -H "Authorization: Bearer $DT" \
  -d '{"status": "in_progress"}' > /dev/null

docker compose exec redis redis-cli XREVRANGE taskflow:task-events:stream + - COUNT 2
docker compose exec -T db psql -U taskflow -d taskflow -c \
  "SELECT id, type, status, recipient_id FROM notification WHERE task_id = $TID ORDER BY id;"
# Run the SELECT again after the next Beat tick (≤ 60s): a TASK_DUE_REMINDER row appears
```

## Expected vs Actual Findings

| Step | Expected | Actual | Status |
| :--- | :--- | :--- | :---: |
| Stack | `make docker-up` starts all 7 services | All running; api, db, mongo, redis healthy | **PASS** |
| Cache | 2nd summary read is a cache hit | TTL kept counting down (29996 -> 29784 ms, not reset); api log `MISS … version=10`, then `HIT … version=10` | **PASS** |
| API latency | Assign responds without waiting on side effects | `200` in 18 ms | **PASS** |
| Invalidation | Assign and status change bump the cache version | `10 -> 11`, then `11 -> 12` | **PASS** |
| Events | `task.assigned` and `task.status_changed` on the stream | Both entries, with the API request id in the payload | **PASS** |
| Celery worker | Outbox row `pending -> sent` | Notification 58 `sent` about 1s after the response | **PASS** |
| Celery Beat | Assignee reminded of the task due today | `TASK_DUE_REMINDER` for task 217 after 25s (next tick) | **PASS** |
| Flower | This run's delivery job and reminder sweep listed | Delivery job for notification 58 `SUCCESS`; sweep with `reminded_task_ids: [217]` | **PASS** |
| Tracing | One request id in api and worker logs | Same id on invalidation, publish, and the worker delivery | **PASS** |

## Evidence

### `make flow-demo`
```text

===========================================================================
  TaskFlow — Session 05 Demo: End-to-End Task Change: API -> Redis -> Celery -> Beat -> Flower
===========================================================================

>> Step 0: Check that every service in the flow is up
  [PASS] api answers at http://localhost:8000
  [PASS] Redis answers at redis://localhost:6379/0
  [PASS] Celery worker online: celery@6da12e3ce67d
  [PASS] Flower answers at http://127.0.0.1:5555

>> Step 1: Create a manager, a developer, a project, and a task due today
  • manager=38 developer=39 project=20 task=217 (due 2026-10-25)

>> Step 2: Read the task summary twice (cache miss, then hit)
  • 1st read 211 ms, 2nd read 210 ms (both include the simulated 200 ms external call, which is never cached)
  [PASS] 1st read stored the summary at taskflow:v1:ws:1:task_summary:v10 (TTL 29996 ms)
  [PASS] 2nd read was a cache hit (TTL 29996 -> 29784 ms, not reset)
  [PASS] 2nd read returned the same metrics
  • api log lines: request a026a1ffe67a4ca7a0f979e1ce18501b (MISS), 57c2b2b4408e4535b03c0f14b78f0318 (HIT)

>> Step 3: Manager assigns the task to the developer
  [PASS] API responded 200 in 18 ms (request id 6f824b10baed4f838537087aa70bceb9)
  [PASS] summary cache invalidated (taskflow:v1:ws:1:task_summary:version 10 -> 11)
  [PASS] task.assigned appended to taskflow:task-events:stream: [{'id': '1792928651159-0', 'event_type': 'task.assigned'}]
  • Waiting up to 30s for the worker to deliver...
  [PASS] Celery worker delivered the assignment notification
  • notification id=58 status=sent recipient=39, 1.0s after the API responded

>> Step 4: Developer starts the task (todo -> in_progress)
  [PASS] API responded 200 in 31 ms
  [PASS] summary cache invalidated again
  [PASS] task.status_changed appended to the stream: [{'id': '1792928652215-0', 'event_type': 'task.status_changed'}]

>> Step 5: Celery Beat's due-task sweep reminds the assignee
  • Beat queues the sweep every 60s; waiting up to 90s...
  [PASS] TASK_DUE_REMINDER created for the task due today
  • reminder id=59 recipient=39 after 25s, payload={'status': 'in_progress', 'task_id': 217, 'due_date': '2026-10-25', 'priority': 'medium', 'is_overdue': False, 'project_id': 20, 'task_title': 'Ship the flow demo 57932a4d', 'workspace_id': 1}

>> Step 6: Flower shows the jobs behind the flow
  [PASS] Flower lists the delivery job for notification 58 as succeeded (state SUCCESS)
  • http://127.0.0.1:5555/task/d283deb1-dc9b-4162-b365-0be0a3556b70
  [PASS] Flower lists the reminder sweep that reminded task 217
  • http://127.0.0.1:5555/task/737e747c-82e9-4bbd-9b27-e763b2d1bf89 result={'status': 'success', 'tasks_checked': 46, 'reminders_created': 1, 'reminders_skipped': 45, 'reminders_failed': 0, 'reminded_task_ids': [217]}

  • Follow the same request id through `make docker-logs s=api` and `make docker-logs s=celery-worker`.

===========================================================================
  TaskFlow — Session 05 Demo: Every part of the flow handled the task change
===========================================================================
```

### One request id across the api and the worker
```text
[2026-10-25 11:44:11,158] [INFO] [6f824b10baed4f838537087aa70bceb9] app.cache.task_summary_cache: Task summary cache INVALIDATED workspace_id=1 version=11
[2026-10-25 11:44:11,159] [INFO] [6f824b10baed4f838537087aa70bceb9] app.events.publisher: Published task.assigned event_id=b1d54e33-4213-42cb-a7a8-c5a803b8ea01 task_id=217: pubsub_receivers=0 stream_entry=1792928651159-0
[2026-10-25 11:44:11,213: INFO/ForkPoolWorker-8] [6f824b10baed4f838537087aa70bceb9] Transitioned pending notification 58 to 'sent' for task 217 to recipient 39.
[2026-10-25 11:44:11,214: INFO/ForkPoolWorker-8] [6f824b10baed4f838537087aa70bceb9] Task app.tasks.notification_tasks.send_task_assignment_notification[d283deb1-dc9b-4162-b365-0be0a3556b70] succeeded in 0.05s
```
`pubsub_receivers=0` because no Pub/Sub consumer was running during this run. The stream
kept the event regardless.

### Stream entries
```text
1792928651159-0  task.assigned
{"event_id":"b1d54e33-…","event_type":"task.assigned","task_id":217,"workspace_id":1,"project_id":20,"actor_id":38,"request_id":"6f824b10baed4f838537087aa70bceb9","data":{"previous_assignee_id":null,"new_assignee_id":39}}
1792928652215-0  task.status_changed
{"event_id":"d21bb366-…","event_type":"task.status_changed","task_id":217,"workspace_id":1,"project_id":20,"actor_id":39,"request_id":"d6068a6217bc4059bd8e41d6910c86d1","data":{"previous_status":"todo","new_status":"in_progress"}}
```

## What We Learned
- **The request path only commits and hands off.** The API answered in under 20 ms; delivery
  took another second, and the reminder waited for Beat. None of that sits in front of the
  user.
- **The request id is the thread through the system.** It goes from the HTTP header into
  the event payload and the Celery headers, so one grep shows the whole story for one change.
- **Each hand-off has its own recovery.** The cache has its TTL, the events have the stream
  backlog, the jobs have the outbox sweep and late acks, and the reminders have the lock and
  dedup. See the failure table in
  [`end-to-end-flow.md`](../../../docs/session-05/end-to-end-flow.md#3-failure-cases-tested).
- **Flower answers "did the job run", the database answers "what did it do".** The sweep's
  result in Flower lists task ids; the `notification` table holds the reminder itself.

## Open Questions
- Should task events go through the outbox too, to close the dual-write gap?
- Is a 5-minute outbox recovery window acceptable for assignment notifications?
- What alerting should replace watching Flower (queue depth, failure rate, Beat liveness)?
