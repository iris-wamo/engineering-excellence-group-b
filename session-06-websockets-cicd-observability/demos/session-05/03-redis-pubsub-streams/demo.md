# Demo 03 — Redis Pub/Sub vs Redis Streams

## Loom Video
- Part 1: <https://www.loom.com/share/ca0489487c8a4f2a987d6958f1d99036>
- Part 2: <https://www.loom.com/share/92395e21b24f4ecd9a8f1ab496866718>

## Background in one minute

- **Redis** is an in-memory data store. It is very fast, and here it carries messages
  between the API and other processes.
- **Pub/Sub** works like a radio broadcast. The API `PUBLISH`es to a channel, and only the
  listeners tuned in at that moment hear it. Redis keeps no copy.
- **Streams** work like a log book. The API `XADD`s each event to the end of a list that Redis
  keeps. A **consumer group** remembers how far it has read. Each worker confirms an event with
  `XACK` once it has handled it; anything not confirmed is handed out again.
- A **consumer** is a separate process that reads events and does something with them. Here
  it records each event on a per-task timeline and counts events by type.

## Objective

Prove three things:

- Task status changes and assignments publish an internal event.
- A consumer receives and processes those events.
- Pub/Sub (fire-and-forget) and Streams (durable) behave differently when the consumer is
  offline or crashes, and processing the same event twice has no duplicate effect.

Design and comparison: [`docs/session-05/redis-pubsub-vs-streams.md`](../../../docs/session-05/redis-pubsub-vs-streams.md).

## Scenario

A manager assigns a task to a developer, and the developer starts it. Both consumers are
online and see both events. Both consumers are then taken offline (a deploy, or a crash).
While they are down, the developer moves the task to `review` and then `done`. When the
consumers come back, which of them knows the task is done?

A second, scripted scenario covers the cases that are hard to time by hand: the same event
delivered twice, and a Streams worker that crashes after processing an entry but before
acknowledging it.

## Commands / Steps Used

Run every command from the `session-05-async-redis-celery/` directory. The demo uses three
terminals. Terminals 2 and 3 run consumers, which keep running until you press Ctrl+C. Run
all other commands in terminal 1, so the variables set in step 3 are still there for later
steps.

### 1. Start the stack (terminal 1)

```bash
make docker-up
```

This starts Postgres, MongoDB, Redis, and the API on `http://localhost:8000`. The API
container runs the migrations itself when it starts. To check that everything is up:

```bash
docker compose ps
```

All four services should show `(healthy)`.

### 2. Start the two consumers (terminals 2 and 3)

Terminal 2, the Pub/Sub consumer:

```bash
make events-pubsub
```

Terminal 3, the Streams consumer:

```bash
make events-streams NAME=worker-1
```

`NAME` keeps the consumer's name the same across restarts, so when it comes back in step 7
it picks up anything it had not acknowledged. Leave both running. They print one line for every event they receive.

### 3. Create a manager, a developer, a project, and a task (terminal 1)

`POST /projects` needs an admin, and the admin role needs an existing project. So this step
inserts the project and the two project roles directly with `psql`, and does everything else
through the API.

```bash
API=http://localhost:8000/api/v1
H='Content-Type: application/json'
SUFFIX=$RANDOM   # keeps emails unique if you run the demo again

# Two users: a manager who assigns work, and a developer who does it
MID=$(curl -s -X POST $API/auth/signup -H "$H" \
  -d "{\"name\": \"Maya Manager\", \"email\": \"maya$SUFFIX@example.com\", \"password\": \"password123\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')
DID=$(curl -s -X POST $API/auth/signup -H "$H" \
  -d "{\"name\": \"Dev Dana\", \"email\": \"dana$SUFFIX@example.com\", \"password\": \"password123\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')

# A project in Workspace 1, with Maya as manager and Dana as member
PID=$(docker compose exec -T db psql -U taskflow -d taskflow -tAq -c \
  "INSERT INTO project (name, slug, workspace_id, created_at, updated_at)
   VALUES ('Events Demo $SUFFIX', 'events-demo-$SUFFIX', 1, NOW(), NOW()) RETURNING id;" | head -1)
docker compose exec -T db psql -U taskflow -d taskflow -qc \
  "INSERT INTO project_user (project_id, user_id, role) VALUES ($PID, $MID, 'manager'), ($PID, $DID, 'member');"

# Log both users in
MT=$(curl -s -X POST $API/auth/login -H "$H" \
  -d "{\"email\": \"maya$SUFFIX@example.com\", \"password\": \"password123\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
DT=$(curl -s -X POST $API/auth/login -H "$H" \
  -d "{\"email\": \"dana$SUFFIX@example.com\", \"password\": \"password123\"}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')

# A task in the project
TID=$(curl -s -X POST $API/tasks -H "$H" -H "Authorization: Bearer $MT" \
  -d "{\"title\": \"Ship task events\", \"project_id\": $PID}" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')

echo "manager=$MID developer=$DID project=$PID task=$TID"
```

The last line should print four numbers. If any of them is empty, check `make docker-logs`.

### 4. Make two changes while both consumers are online (terminal 1)

```bash
# Maya assigns the task to Dana: publishes task.assigned
curl -s -X POST $API/tasks/$TID/assign -H "$H" -H "Authorization: Bearer $MT" \
  -H "X-Request-ID: demo-assign-1" -d "{\"assignee_id\": $DID}"; echo

# Dana starts it: publishes task.status_changed (todo -> in_progress)
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -H "Authorization: Bearer $DT" \
  -H "X-Request-ID: demo-status-1" -d '{"status": "in_progress"}'; echo
```

Terminals 2 and 3 should each print two `PROCESSED` lines.

### 5. Take both consumers offline

Press **Ctrl+C** in terminal 2 and in terminal 3.

### 6. Make two more changes while nobody is listening (terminal 1)

```bash
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -H "Authorization: Bearer $DT" \
  -H "X-Request-ID: offline-1" -d '{"status": "review"}'; echo
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -H "Authorization: Bearer $DT" \
  -H "X-Request-ID: offline-2" -d '{"status": "done"}'; echo

# What the API logged: pubsub_receivers=0 means Pub/Sub dropped the event
docker compose logs api | grep Published | tail -2

# The stream kept them: "lag" is the number of entries the group has not read yet
docker compose exec redis redis-cli XINFO GROUPS taskflow:task-events:stream
```

### 7. Bring both consumers back

Run `make events-pubsub` in terminal 2 and `make events-streams NAME=worker-1` in terminal 3 again.

- Terminal 3 (Streams) immediately prints `PROCESSED` for the `review` and `done` events.
- Terminal 2 (Pub/Sub) prints only `Subscribed`. Those two events are gone.

### 8. Compare what each consumer applied (terminal 1)

```bash
docker compose exec redis redis-cli HGETALL taskflow:events:pubsub:counts
docker compose exec redis redis-cli HGETALL taskflow:events:streams:counts
docker compose exec redis redis-cli XINFO GROUPS taskflow:task-events:stream
```

Pub/Sub shows 2 events and Streams shows 4. The group now has `pending 0` and `lag 0`. For an
interactive Redis shell, use `make redis-cli` and type the same commands without the
`docker compose exec redis redis-cli` prefix.

### 9. Scripted duplicate and crash scenarios (terminal 1)

```bash
make events-demo
```

The script runs its own consumers, so terminals 2 and 3 are not needed. It uses separate
`taskflow:demo:*` keys and does not touch the events above.

### 10. Tests (terminal 1)

```bash
uv run pytest tests/unit/events tests/integration/events tests/integration/api/test_task_events_api.py -v
```

These need Postgres, MongoDB, and Redis running (step 1).

## Expected Behavior

- Each change publishes one event to the channel and one to the stream.
- While both consumers are offline, Pub/Sub drops the events (`pubsub_receivers=0`) and the
  stream keeps them (group `lag` grows).
- On restart, the Streams consumer processes the backlog. The Pub/Sub consumer never sees it.
- An event delivered a second time is logged as `DUPLICATE`, and counts and timelines do not
  change.
- An entry left unacknowledged by a crashed worker is claimed by another worker and
  acknowledged, with no double effect.

## Actual Findings

All of the above matched. After the run, the Streams consumer had applied **4 of 4** events
for the task and the Pub/Sub consumer **2 of 4**. The two missing events are gone for good;
nothing in Redis can bring them back. In the scripted run, both duplicates (a republished
event, and a redelivery after a crash before `XACK`) changed nothing.

## Evidence

### Sample event payload (from the stream, published by the API)

```
127.0.0.1:6379> XRANGE taskflow:task-events:stream - + COUNT 1
1792066404705-0
event_type
task.assigned
payload
{"event_id":"733658d5-4f15-4af6-bd4c-2a686731e3e4","event_type":"task.assigned","schema_version":1,"occurred_at":"2026-10-15T12:13:24.702630Z","task_id":204,"workspace_id":1,"project_id":8,"actor_id":14,"request_id":"demo-assign-1","data":{"previous_assignee_id":null,"new_assignee_id":15}}
```

### Producer log (API container)

The request id in brackets is the `X-Request-ID` of the call. It is also stored in the event.

```
[2026-10-15 12:13:24,706] [INFO] [demo-assign-1] app.events.publisher: Published task.assigned event_id=733658d5-4f15-4af6-bd4c-2a686731e3e4 task_id=204: pubsub_receivers=1 stream_entry=1792066404705-0
[2026-10-15 12:13:24,725] [INFO] [demo-status-1] app.events.publisher: Published task.status_changed event_id=de15344d-3fb3-48e2-af99-dc7366554a12 task_id=204: pubsub_receivers=1 stream_entry=1792066404725-0
--- consumers stopped ---
[2026-10-15 12:13:34,658] [INFO] [offline-1] app.events.publisher: Published task.status_changed event_id=110a2655-2a22-4b7f-a33b-8cd7aeabf967 task_id=204: pubsub_receivers=0 stream_entry=1792066414657-0
[2026-10-15 12:13:34,686] [INFO] [offline-2] app.events.publisher: Published task.status_changed event_id=362d85b8-1008-4e30-ae35-53c32d487819 task_id=204: pubsub_receivers=0 stream_entry=1792066414686-0
```

`pubsub_receivers=0` means nobody received those two Pub/Sub messages.

### Stream group while both consumers were offline

`redis-cli` prints these as alternating lines; they are shown here as pairs.

```
127.0.0.1:6379> XINFO GROUPS taskflow:task-events:stream
name               task-event-processors
consumers          1
pending            0
last-delivered-id  1792066404725-0
entries-read       2
lag                2          <- the two offline events, waiting
```

### Pub/Sub consumer log (`make events-pubsub`)

Shortened for reading: the date, log level, and logger name are removed, and event ids are
cut after 8 characters (`…`). The full lines look like the producer log above.

```
[17:13:08,795] [pubsub] Subscribed to channel taskflow:task-events
[17:13:24,714] [pubsub] PROCESSED task.assigned event_id=733658d5-… task_id=204 actor_id=14 data={'previous_assignee_id': None, 'new_assignee_id': 15}
[17:13:24,727] [pubsub] PROCESSED task.status_changed event_id=de15344d-… task_id=204 actor_id=15 data={'previous_status': 'todo', 'new_status': 'in_progress'}
[17:13:32,749] [pubsub] Unsubscribed from channel taskflow:task-events
--- offline: review and done happen here ---
[17:13:42,525] [pubsub] Subscribed to channel taskflow:task-events
                         (nothing: the review and done events were never stored)
[17:13:46,536] [pubsub] Unsubscribed from channel taskflow:task-events
```

### Streams consumer log (`make events-streams NAME=worker-1`)

Shortened for reading: the date, log level, and logger name are removed, and event ids are
cut after 8 characters (`…`). The full lines look like the producer log above.

```
[17:13:08,796] [streams] Created consumer group task-event-processors on taskflow:task-events:stream
[17:13:08,796] [streams] Consumer worker-1 joined group task-event-processors on taskflow:task-events:stream
[17:13:24,709] [streams] PROCESSED task.assigned event_id=733658d5-… task_id=204 actor_id=14 data={'previous_assignee_id': None, 'new_assignee_id': 15}
[17:13:24,727] [streams] PROCESSED task.status_changed event_id=de15344d-… task_id=204 actor_id=15 data={'previous_status': 'todo', 'new_status': 'in_progress'}
[17:13:32,972] [streams] Consumer worker-1 stopped
--- offline: review and done happen here ---
[17:13:42,525] [streams] Consumer worker-1 joined group task-event-processors on taskflow:task-events:stream
[17:13:42,529] [streams] PROCESSED task.status_changed event_id=110a2655-… task_id=204 actor_id=15 data={'previous_status': 'in_progress', 'new_status': 'review'}
[17:13:42,530] [streams] PROCESSED task.status_changed event_id=362d85b8-… task_id=204 actor_id=15 data={'previous_status': 'review', 'new_status': 'done'}
[17:13:46,682] [streams] Consumer worker-1 stopped
```

Afterwards, `XINFO GROUPS` showed `pending 0` and `lag 0`.

### What each consumer applied

```
127.0.0.1:6379> HGETALL taskflow:events:pubsub:counts
task.assigned        1
task.status_changed  1

127.0.0.1:6379> HGETALL taskflow:events:streams:counts
task.assigned        1
task.status_changed  3
```

### Duplicates and crash before XACK (`make events-demo`, excerpt)

Shortened in the same way. Run `make events-demo` to see the full output.

```
4. The same event (same event_id) published again
Published task.status_changed event_id=9844ef7c-… task_id=101: pubsub_receivers=1 stream_entry=1792066452196-0
[demo:streams] DUPLICATE task.status_changed event_id=9844ef7c-… task_id=101 …
[demo:pubsub]  DUPLICATE task.status_changed event_id=9844ef7c-… task_id=101 …

5. Streams worker processes an entry, then crashes before XACK
[demo:streams] PROCESSED task.unassigned event_id=e25faa7f-… task_id=103 …
worker-b crashed before XACK of 1792066453243-0
Pending entries in group: 1 (owned by [{'name': 'worker-b', 'pending': 1}])
[WARNING] [streams] Redelivering pending entry 1792066453243-0 (attempt 2, previously with worker-b)
[demo:streams] DUPLICATE task.unassigned event_id=e25faa7f-… task_id=103 …
Pending entries in group after recovery: 0

Result: events applied per consumer
event type              pubsub  streams
task.status_changed          1        3
task.assigned                0        1
task.unassigned              0        1
total                        1        5   (5 distinct events; Pub/Sub was offline for 4 of them)
```

The stream holds 6 entries for 5 distinct events because one was republished, and the
crashed entry was delivered twice. Neither duplicate changed the counts.

### Tests

```
$ uv run pytest tests/unit/events tests/integration/events tests/integration/api/test_task_events_api.py -q
..............................                                           [100%]
30 passed in 12.58s
```

That is 5 unit tests, 17 publisher and consumer tests, and 8 API tests. The full suite
(`uv run pytest`) passed with 302 tests.

## What We Learned

- **Pub/Sub is at most once.** An offline consumer, a dropped connection, or a crash
  mid-handler loses the message with no trace except the publisher's receiver count. It suits
  "refresh now" signals, not facts that must be acted on.
- **Streams with consumer groups are at least once.** The group remembers where it is, and
  `XACK` after processing means a crash causes a redelivery instead of a loss.
- **At least once means duplicates.** A consumer must be idempotent. Here that is a dedup
  marker on `event_id`, written atomically with the effect in one Lua script. Writing the
  marker and the effect as separate steps would risk either a lost effect or a double one.
- **Durable transport is not end to end.** The event is published after the database commit,
  so a Redis outage at that moment loses it (the request still succeeds). Closing that gap
  needs a transactional outbox.

## Open Questions

- Should the transactional outbox land with notifications (#101), or as its own change?
- How large should the stream's `MAXLEN` be? It has to cover the longest consumer outage
  at peak event rate.
- Do any consumers need per-task ordering when several Streams workers share a group?
