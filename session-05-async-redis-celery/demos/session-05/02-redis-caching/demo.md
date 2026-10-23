# Demo 02 — Redis Caching and Cache Invalidation

## Loom Video
- **Loom Video Status**: **MANUAL FOLLOW-UP REQUIRED**. No recording exists yet; record a short walkthrough of the steps below and paste the URL here.
- **Loom Link**: `[Manual Follow-up: insert Loom recording URL]`

## Objective
Show that caching the task summary in Redis avoids repeating the expensive read, that a task write clears the cached value so the next read is fresh, and that an unrefreshed value expires after its TTL.

## Scenario
A dashboard polls `GET /api/v1/tasks/summary` for a workspace. The metrics query runs on every poll, but the data only changes when tasks change. We cache it per workspace and invalidate on writes.

## Commands / Steps Used
```bash
make docker-up
uv run python scripts/demo_cache.py        # miss, hit, invalidation, expiry (TTL set to 3s)
uv run pytest tests/unit/cache tests/integration/cache -v
make redis-cli                             # then: KEYS taskflow:v1:ws:*
```

## Expected Behavior
1. First request is a MISS, fills the entry; the next is a HIT served from Redis.
2. Creating, re-statusing, assigning or importing a task bumps the workspace version; the next request is a MISS with fresh data.
3. With no writes, the entry expires after the TTL and the next request is a MISS again.

## Actual Findings
Output of `scripts/demo_cache.py` against the dev database (ids and timings from one real run; the first call includes cold-start cost):

## Evidence
```
 1. MISS, then HIT
  GET /tasks/summary -> 200 in 100.0 ms  total_count=73 todo=22
  redis> TTL taskflow:v1:ws:1:task_summary:v0  ->  3   (filled by the miss)
  GET /tasks/summary -> 200 in 5.1 ms  total_count=73 todo=22

 2. A task write clears the cache
  redis> GET taskflow:v1:ws:1:task_summary:version  ->  '1'
  redis> TTL taskflow:v1:ws:1:task_summary:v1  ->  -2   (version bumped, new entry not written yet)
  GET /tasks/summary -> 200 in 9.5 ms  total_count=74 todo=23

 3. Expiry after the 3s TTL
  sleeping 4s ...
  redis> TTL taskflow:v1:ws:1:task_summary:v1  ->  -2   (expired)
  GET /tasks/summary -> 200 in 13.2 ms  total_count=74 todo=23
```

Log lines for the same run:
```
Task summary cache MISS workspace_id=1 version=0
Task summary cache HIT workspace_id=1 version=0
Task summary cache INVALIDATED workspace_id=1 version=1
Task summary cache MISS workspace_id=1 version=1
Task summary cache HIT workspace_id=1 version=1
Task summary cache MISS workspace_id=1 version=1   (after the TTL)
```
`total_count` goes from 73 to 74 right after the task is created, so the write was visible on the next read.

## What We Learned
1. Versioning the key beats deleting it: a slow reader cannot write an old result over newer data.
2. The TTL is a safety net for lost invalidations and for date-dependent values like `overdue_count`.
3. A cache that fails open costs latency, never correctness or availability.
4. Cache the shared, expensive part and keep per-request parts (the external call) live.

## Open Questions
1. Should invalidation also happen on project or workspace membership changes, or is the TTL enough there?
2. If the summary is cached for much longer, should invalidation move to the existing task events stream so a lost Redis call can be replayed?
