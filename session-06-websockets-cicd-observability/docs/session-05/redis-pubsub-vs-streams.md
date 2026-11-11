# Redis Pub/Sub vs Redis Streams

Issue **#100**. When a task's status changes or a task is assigned, TaskFlow publishes an
internal event. Every event goes to **both** Redis Pub/Sub and a Redis Stream, and one consumer
reads each, so the two can be compared on the same traffic.

Sending notifications based on these events is out of scope here (#101).

---

## Background: Redis, Pub/Sub, and Streams

**Redis** is an in-memory data store: a server that holds data in RAM and answers commands in
well under a millisecond. It has several data types (strings, hashes, lists, streams) and
can also pass messages between processes. TaskFlow runs it as the `redis` service in
`compose.yaml`. Here it carries task events from the API to background consumers, so the API
does not have to do that follow-up work inside the request.

Some terms used below:

| Term | Meaning |
| :--- | :--- |
| **Event** | A record that something happened, for example "task 204 moved from `review` to `done`, by user 15, at 12:13". |
| **Producer / publisher** | The code that sends events. Here, the API after it saves a change. |
| **Consumer** | A separate process that receives events and acts on them. |
| **Idempotent** | Doing it twice has the same result as doing it once. |

**Redis Pub/Sub** (publish/subscribe) works like a live radio broadcast:

- A consumer `SUBSCRIBE`s to a channel, `taskflow:task-events` in this project.
- The producer `PUBLISH`es a message to that channel.
- Redis passes the message to every subscriber connected at that moment, then forgets it.
- If nobody is listening, the message is lost. Nothing is stored, and nothing can be replayed.

**Redis Streams** work like a log book that Redis keeps:

- The producer appends each event with `XADD`, and Redis gives the entry an ordered id, for
  example `1792066404705-0`.
- A **consumer group** is a named reader of the stream that remembers how far it has read.
  Consumers in the group read with `XREADGROUP`, and each entry goes to one of them.
- When a consumer has finished an entry, it confirms with `XACK`. Until then the entry sits in
  the group's **pending list**, and can be handed to another consumer if the first one dies.
- Because entries are stored, a consumer that was offline catches up when it comes back.

The rest of this document shows, with real runs, what that difference means for TaskFlow.

---

## 1. What is published, and when

| Trigger | Event type | `data` |
| :--- | :--- | :--- |
| `POST /tasks` creates a task with an assignee | `task.assigned` | `previous_assignee_id` (null), `new_assignee_id` |
| `PATCH /tasks/{id}/status` changes the status | `task.status_changed` | `previous_status`, `new_status` |
| `POST /tasks/{id}/assign` changes the status | `task.status_changed` | `previous_status`, `new_status` |
| `POST /tasks/{id}/assign` sets a new assignee | `task.assigned` | `previous_assignee_id`, `new_assignee_id` |
| `POST /tasks/{id}/assign` clears the assignee | `task.unassigned` | `previous_assignee_id`, `new_assignee_id` (null) |

Events are only published for real changes:

- Asking for the status the task already has publishes nothing.
- A rejected transition (for example `todo → done`) publishes nothing.
- A rolled-back assignment (including `simulate_failure`) publishes nothing.

Events are published **after** the database commit
([`TaskService`](../../app/services/task_service.py)), so a consumer never sees a change that
was later rolled back.

```
 API request ──► TaskService ──► COMMIT (Postgres) ──► TaskEventPublisher
                                                         │  one pipeline per request
                                   ┌─────────────────────┴───────────────────────┐
                                   ▼                                             ▼
                     PUBLISH taskflow:task-events            XADD taskflow:task-events:stream
                                   │                                             │
                     only subscribers connected now            stored; consumer group
                                   │                           "task-event-processors"
                                   ▼                                             ▼
                       PubSubTaskEventConsumer                  StreamTaskEventConsumer
                                   │                                (XREADGROUP / XACK)
                                   └──────────────► TaskEventProcessor ◄──────────┘
                                                (idempotent, per-transport keys)
```

Code: [`app/events/`](../../app/events/). The consumers run as standalone processes:
`make events-pubsub` and `make events-streams`.

---

## 2. Payload design

A real event published by the API (`POST /tasks/204/assign`):

```json
{
  "event_id": "733658d5-4f15-4af6-bd4c-2a686731e3e4",
  "event_type": "task.assigned",
  "schema_version": 1,
  "occurred_at": "2026-10-15T12:13:24.702630Z",
  "task_id": 204,
  "workspace_id": 1,
  "project_id": 8,
  "actor_id": 14,
  "request_id": "demo-assign-1",
  "data": { "previous_assignee_id": null, "new_assignee_id": 15 }
}
```

| Field | Why it is there |
| :--- | :--- |
| `event_id` | UUID4 created by the publisher. This is the **identity consumers deduplicate on**. If the same event is delivered again, it has the same id. A new change always gets a new id. |
| `event_type` | Namespaced (`task.*`) so other entities can add their own events later. Consumers route on it without parsing `data`. |
| `schema_version` | Lets the payload change later without breaking consumers that are already deployed. A consumer can reject or adapt versions it does not know. |
| `occurred_at` | UTC timestamp of the change ("when"). Set by the producer, not the transport. Redelivery does not change it. |
| `task_id`, `project_id`, `workspace_id` | What changed, and the tenant it belongs to. Consumers can scope work per workspace without querying Postgres. |
| `actor_id` | Who made the change. `null` only if the API had no authenticated user. |
| `request_id` | The `X-Request-ID` of the API call. The same id appears in the API log line that published the event, so logs can be traced across services. |
| `data` | Before and after values. Consumers can act on the event without reading the task again, and the event still describes what happened even if the task changes again before the event is processed. |

The model is [`TaskEvent`](../../app/events/schemas.py), a frozen Pydantic model serialized as
JSON. A stream entry stores it as `{"event_type": ..., "payload": <json>}`. The extra
`event_type` field means the stream can be inspected with `XRANGE` without decoding JSON.

---

## 3. Delivery guarantees

### Redis Pub/Sub: fire-and-forget, at most once

- `PUBLISH` pushes the message to the clients subscribed **at that moment** and returns how many
  received it. Redis stores nothing.
- **If no consumer is subscribed, the message is dropped.** The publisher can see this happen
  (`pubsub_receivers=0` in the log), but it cannot be undone.
- If a subscriber crashes while processing, or its connection drops, any message in flight is
  lost. It cannot be acknowledged or replayed.
- Redis disconnects a slow subscriber whose output buffer grows too large
  (`client-output-buffer-limit pubsub`). Its messages are lost too.
- Every subscriber gets every message. More subscribers means more copies of the work, not
  shared work.

### Redis Streams with a consumer group: durable, at least once

- `XADD` appends the event to a log that Redis keeps, which is persisted here by AOF in
  `compose.yaml`. `MAXLEN ~ 10000` caps its size.
- The consumer group stores its read position (`last-delivered-id`). Events added while every
  consumer is offline show up as **lag**, and are read when a consumer returns.
- `XREADGROUP ... >` delivers each entry to **one** consumer in the group. The entry stays in
  the group's **Pending Entries List (PEL)** until that consumer sends `XACK`.
- [`StreamTaskEventConsumer`](../../app/events/consumers.py) acknowledges an entry only
  **after** it has been processed:
  - **Crash before XACK.** The entry stays pending. Every 30 s each consumer claims
    (`XPENDING` + `XCLAIM`) entries that have been idle that long, for example ones left by a
    consumer that died. A consumer restarted under the same name
    (`make events-streams NAME=worker-1`) also retries its own pending entries immediately on
    startup, however many there are. Without `NAME`, each process is named `<host>-<pid>`,
    so two consumers on one machine never share a name and never take over each other's
    in-flight entries. The cost is that each restart joins the group as a new consumer.
    Old names stay listed in `XINFO CONSUMERS` (their pending entries are still reclaimed
    after 30 s). Remove them with `XGROUP DELCONSUMER` once they show `pending 0`, or use a
    fixed `NAME` per worker.
  - **Processing raises.** The entry is not acknowledged and is retried the same way.
  - **Poison message.** After `max_deliveries` (5) attempts, or if the payload is invalid,
    the entry is copied to `taskflow:task-events:dead-letter` and acknowledged in one
    `MULTI`/`EXEC` transaction, so it cannot end up dead-lettered twice. One bad event cannot
    block the rest.
  - **Redis errors.** If Redis drops the connection or refuses a command (for example
    `OOM` when it is full), the worker logs the error and restarts its loop after 2 s. It
    does not exit, which would leave events unprocessed until someone noticed.
- The group is created at id `0` rather than `$`, so events published before the group
  existed are processed too.
- If the stream or the group disappears while a consumer runs (`DEL`, `FLUSHDB`, or Redis
  restarting without its data), the next read fails with `NOGROUP`. The consumer then
  recreates the group and keeps going instead of exiting.
- If `MAXLEN` trims an entry that is still pending, its event is lost. The consumer logs a
  warning naming the entry when it tries to reclaim it.

"At least once" means **a consumer can see the same event more than once**. That is the cost of
not losing events, and it is why the processor must be idempotent.

---

## 4. Handling the same event twice

Ways an event can be delivered twice:

1. The consumer processes a stream entry and crashes before `XACK`. The entry is redelivered.
2. Processing succeeds but `XACK` fails, for example because the network drops. The entry is
   redelivered.
3. The publisher (or a future outbox relay) retries and sends the same event again. Both
   transports deliver it twice.

[`TaskEventProcessor`](../../app/events/processor.py) does its work in one Lua script, which
Redis runs atomically:

```lua
if not redis.call('SET', processed_key, '1', 'NX', 'EX', ttl) then
    return 0            -- seen before: duplicate, change nothing
end
redis.call('HINCRBY', counts_key, event_type, 1)    -- the actual effect
redis.call('RPUSH', timeline_key, entry)
redis.call('LTRIM', timeline_key, -100, -1)         -- keep the latest 100 entries
return 1
```

- **The dedup marker and the effect are written together.** Writing the marker first and the
  effect second could lose the effect if the consumer crashed in between. Writing the effect
  first could apply it twice. The script removes both gaps.
- The marker key is `taskflow:events:<consumer>:processed:<event_id>`. It is per consumer, so
  the Pub/Sub and Streams consumers keep separate results.
- Markers expire after 7 days. That is far longer than the redelivery window, which is minutes.
- A duplicate is logged as `DUPLICATE` and **still acknowledged**. Otherwise it would be
  redelivered forever.

If the effect moves outside Redis later (for example, writing a notification row to Postgres in
#101), use the same pattern there: a unique constraint on `event_id` inserted in the same
transaction as the effect.

---

## 5. Consumer offline: what actually happens

Taken from `make events-pubsub` / `make events-streams` against the API. Full logs are in
[`demos/session-05/03-redis-pubsub-streams/demo.md`](../../demos/session-05/03-redis-pubsub-streams/demo.md).

| Step | Pub/Sub consumer | Streams consumer |
| :--- | :--- | :--- |
| Both online, task assigned and moved to `in_progress` | processes 2 | processes 2 |
| Both stopped, task moved to `review` then `done` | `PUBLISH` returns 0, so both events are dropped | group `lag=2`: both events are kept |
| Both restarted | **receives nothing**: the 2 events are gone | **processes the 2 backlog events** immediately, `lag=0`, `pending=0` |
| Totals | 2 of 4 | 4 of 4 |

---

## 6. Comparison

| | Pub/Sub | Streams (consumer group) |
| :--- | :--- | :--- |
| Storage | None | Append-only log, trimmed by `MAXLEN` |
| Consumer offline | Messages lost | Messages wait; consumer catches up |
| Guarantee | At most once | At least once |
| Acknowledgement | None | `XACK`; unacknowledged entries stay pending |
| Crash mid-processing | Message lost | Redelivered (`XCLAIM`) |
| Duplicates | Only if the publisher resends | Expected; consumer must be idempotent |
| Fan-out | Every subscriber gets every message | One consumer per group gets each entry; add groups for fan-out |
| Scaling out | Every subscriber does all the work | Consumers in a group share the work |
| Replay / audit | Impossible | `XRANGE` any range still in the stream |
| Poison messages | Lost | Retry count in PEL, then dead-letter |
| Latency / overhead | Lowest; no memory held | Slightly higher; memory grows with stream length |
| Complexity | Very low | Groups, PEL, claiming, trimming |

**When to use which**

- **Pub/Sub** fits signals that only matter right now and are cheap to lose. Examples: "refresh
  this dashboard", cache invalidation broadcasts to every API instance, live typing
  indicators. A missed message is corrected by the next one.
- **Streams** fit events that must eventually be handled exactly once in effect. Examples:
  sending a notification, updating a projection, auditing, or triggering a Celery job. TaskFlow
  task events belong here, and the notification work in #101 should consume the stream.

---

## 7. Known gap: publishing after commit (dual write)

The commit and the publish are two separate writes to two systems. If Redis is down, or the
process dies between `COMMIT` and `XADD`, the task change is saved but **its event is never
published**. Streams cannot help with this, because the event never reached Redis.

The current behavior is deliberate. `publish_task_events` logs the error and the API request
still succeeds (covered by `test_redis_outage_does_not_fail_the_request`). Failing a request
whose change is already committed would be worse.

The outage must also not make the request slow. The API's Redis client uses 1 s timeouts and
no retries, so an unreachable Redis adds about a second to the request. With redis-py's
default policy (10 retries with backoff), the same request waited about 24 s.

The two transports are written by separate commands, so one can fail while the other
succeeds, for example if the stream key holds the wrong type. The publisher records each
transport's outcome per event and logs the failed one by name. It does not report the whole
batch as lost.

The fix is a **transactional outbox**:

1. Insert the event into an outbox table **in the same transaction** as the task change.
2. A relay process (for example a Celery Beat job) reads unsent rows, `XADD`s them, and marks
   them sent.

The relay may resend after a crash. That is fine: the event keeps its `event_id`, and consumers
already deduplicate on it. The existing `notification` table with `status="pending"` is already
an outbox of this kind, and #101 can extend it.

---

## 8. Running it

Start the stack, then run each consumer in its own terminal. Both keep running until you press
Ctrl+C.

```bash
make docker-up          # terminal 1: Postgres, MongoDB, Redis, and the API
```

```bash
make events-pubsub      # terminal 2
```

```bash
make events-streams NAME=worker-1   # terminal 3
```

Then change task statuses or assignments through the API, and stop and restart the consumers
to see the difference. The copy-paste walkthrough, which creates the users, the project and the
task, is in
[`demos/session-05/03-redis-pubsub-streams/demo.md`](../../demos/session-05/03-redis-pubsub-streams/demo.md).

To run the whole comparison as a script, with no API calls and no extra terminals:

```bash
make events-demo
```

To inspect Redis, open a shell with `make redis-cli` and type any of these:

```
XLEN taskflow:task-events:stream
XINFO GROUPS taskflow:task-events:stream
XPENDING taskflow:task-events:stream task-event-processors
XRANGE taskflow:task-events:dead-letter - +
HGETALL taskflow:events:pubsub:counts
HGETALL taskflow:events:streams:counts
LRANGE taskflow:events:streams:task:204:timeline 0 -1
```

| Command | Shows |
| :--- | :--- |
| `XLEN` | How many events the stream holds |
| `XINFO GROUPS` | The group's `lag` (not yet read), `pending` (read but not acknowledged), and `last-delivered-id` |
| `XPENDING` | Pending entries and which consumer holds them |
| `XRANGE …dead-letter` | Events moved aside after too many failed attempts, or with a bad payload |
| `HGETALL …counts` | How many events of each type a consumer applied |
| `LRANGE …timeline` | The events applied to one task, in order. Replace `204` with your task id |

To run one command without opening a shell, prefix it with `docker compose exec redis
redis-cli`, for example `docker compose exec redis redis-cli XLEN taskflow:task-events:stream`.

Settings (`.env` / environment): `REDIS_URL`, plus `TASK_EVENTS_CHANNEL`,
`TASK_EVENTS_STREAM`, `TASK_EVENTS_STREAM_GROUP`, `TASK_EVENTS_STREAM_MAXLEN`, and
`TASK_EVENTS_DEAD_LETTER_STREAM`, which have defaults in
[`app/core/config.py`](../../app/core/config.py).

## 9. Tests

| File | Covers |
| :--- | :--- |
| `tests/unit/events/test_task_event_schema.py` | Payload fields, assigned vs unassigned, unique ids, request id, JSON round trip |
| `tests/unit/app/test_lifespan.py` | Shutdown closes Redis even if closing Mongo fails |
| `tests/unit/db/test_redis_client.py` | The API's Redis client fails fast; clients of closed event loops are dropped; the test database URL keeps credentials and options |
| `tests/integration/events/test_publisher.py` | Stream entry written, subscriber receives, dropped with no subscriber, ordering, Redis outage swallowed, unreachable Redis costs under 3 s, a failed XADD is reported per event and transport |
| `tests/integration/events/test_pubsub_consumer.py` | Online consumer processes; offline events lost; same event twice applied once; malformed message dropped; connection closed even when unsubscribe fails |
| `tests/integration/events/test_stream_consumer.py` | Offline backlog processed and acked; crash before XACK redelivered and skipped; republished event applied once; failure retried; max deliveries and malformed entries dead-lettered; deleted group recreated; trimmed pending entry reported, but not one claimed by another consumer; timeline capped; a pending backlog larger than one page recovered in one call, each failing entry retried once per call; worker restarts after any Redis error but not after a programming error |
| `tests/integration/api/test_task_events_api.py` | API status change, assignment, unassignment, and combined changes publish the right events; rejected, no-op, or rolled-back changes publish nothing; Redis outage does not fail the request; creating a task with an assignee publishes `task.assigned` |

The tests use Redis logical database 15 (see `tests/fixtures/redis.py`), which is flushed
around each test.

## 10. Open questions

- **Ordering.** With several Streams consumers in one group, two events for the same task can
  be processed in parallel and out of order. If a consumer needs per-task order, it can check
  `occurred_at` or a per-task version, or the work can be partitioned by task.
- **Stream retention.** `MAXLEN ~ 10000` is a guess. It must hold more than the longest
  expected consumer outage at peak event rate, or events are trimmed before they are read.
  A consumer that finds a pending entry already trimmed only logs a warning and acknowledges
  it; a metric and an alert would be better.
- **Outbox** (section 7). Should it land with #101 or as its own change?
