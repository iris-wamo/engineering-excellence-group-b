# Redis Caching and Invalidation

Caches the workspace task summary (`GET /api/v1/tasks/summary` and `/summary/blocking`) in
Redis. Code: `app/cache/task_summary_cache.py`; hooked into `TaskService` and
`TaskImportService`.

## What is cached

Only the aggregated database metrics (counts by status, overdue, assigned, total): one SQL
query per workspace. The simulated external call is **not** cached. It is a per-request
demo controlled by `external_delay` and `external_timeout`, and caching it would hide those
parameters. Both summary endpoints share one entry because they read the same metrics.

## Key naming

| Key | Value |
|---|---|
| `taskflow:v1:ws:{workspace_id}:task_summary:v{version}` | JSON metrics, with a TTL |
| `taskflow:v1:ws:{workspace_id}:task_summary:version` | integer counter, no TTL |

- `taskflow:` namespaces the app on a shared Redis, `v1` lets us change the stored shape
  without reading old entries, and the workspace id keeps tenants apart.
- A missing version key means version `0`.

## TTL

`TASK_SUMMARY_CACHE_TTL_SECONDS`, default **30s**. It is a safety net, not the freshness
mechanism: writes invalidate immediately. 30s keeps the worst case small if an invalidation
is lost (Redis down during a write), and it is also what makes `overdue_count` correct
across midnight, since that value changes with the date and no task write.

## Invalidation strategy

After the database commit of a task create, status change, assignment, or import, the
workspace's version counter is incremented (`INCR`). Readers look up the current version,
then the entry for that version, so the old entry is never read again. It is not deleted; it
expires on its own TTL.

Why a version instead of `DELETE`: a reader that queried the database before a write can
store its result after the write's invalidation. With a deleted key that stale result would
be cached for a full TTL. With a version, the reader stores under the version it read
before querying, which is no longer current, so the stale result is unreachable
(`test_a_summary_computed_before_a_write_is_never_served_after_it`).

Invalidation runs after the commit, so a rolled-back write does not clear the cache, and it
never raises, so a Redis outage cannot fail a write that is already committed.

## Stale-cache risks

- **Lost invalidation** (Redis unreachable during the write): stale for at most the TTL. A
  warning is logged with that bound.
- **Version key lost** (Redis restart without persistence, eviction): the version resets to
  0 and could match an older entry, but entries live at most one TTL, so the exposure is
  the same bound.
- **A write path that forgets to invalidate**: stale for the TTL. Any new code that changes
  task status, assignee, due date, or workspace must call `invalidate_summary`.
- **Reads between commit and invalidation**: a request in that gap can still be served the
  old value for a few milliseconds.

## Redis down

Every cache function fails open: a lookup is a miss, so the request is served from the
database with the same result, only slower. Redis timeouts are about a second
(`app/db/redis.py`).

## What should not be cached

- Anything per user or permission dependent. The summary is per workspace and the same for
  every member.
- Responses with side effects, or data that must be read-your-writes consistent.
- The external call result here, because the demo needs to control it per request.
- Data where a 30s stale read is not acceptable.

## Observing it

`make redis-cli`, then `KEYS taskflow:v1:ws:*`, `GET taskflow:v1:ws:1:task_summary:version`,
`TTL <key>`. Log lines: `Task summary cache HIT/MISS/INVALIDATED workspace_id=... version=...`.
`uv run python scripts/demo_cache.py` walks through miss, hit, invalidation, and expiry.
