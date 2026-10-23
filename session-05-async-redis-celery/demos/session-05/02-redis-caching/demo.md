# Demo 02 — Redis Caching and Cache Invalidation

## Loom Video
- **Loom Link**: `[Manual Follow-up: insert Loom recording URL]`

## Objective
Cache the task summary in Redis, clear it when a task changes, and let it expire after its TTL.

## Scenario
A dashboard polls `GET /api/v1/tasks/summary`. The query runs on every poll, but the data only changes when tasks change.

## Commands / Steps Used
```bash
uv run python scripts/demo_cache.py   # miss, hit, write, expiry (TTL set to 3s)
uv run pytest tests/unit/cache tests/integration/cache -v
make redis-cli                        # KEYS taskflow:v1:ws:*
```

## Expected Behavior
1. First request is a miss, the next is a hit.
2. Creating, moving, assigning or importing a task makes the next request a miss with fresh data.
3. With no writes, the entry expires after the TTL.

## Actual Findings
All three behaved as expected. The write was visible on the very next read (`total_count` 73 to 74).

## Evidence
```
1. MISS, then HIT
  GET /tasks/summary -> 200 in 100.0 ms  total_count=73
  redis> TTL taskflow:v1:ws:1:task_summary:v0  ->  3
  GET /tasks/summary -> 200 in 5.1 ms  total_count=73

2. A task write clears the cache
  redis> GET taskflow:v1:ws:1:task_summary:version  ->  '1'
  GET /tasks/summary -> 200 in 9.5 ms  total_count=74

3. Expiry after the 3s TTL
  redis> TTL taskflow:v1:ws:1:task_summary:v1  ->  -2
  GET /tasks/summary -> 200 in 13.2 ms  total_count=74
```

```
Task summary cache MISS workspace_id=1 version=0
Task summary cache HIT workspace_id=1 version=0
Task summary cache INVALIDATED workspace_id=1 version=1
Task summary cache MISS workspace_id=1 version=1
```

## What We Learned
1. A version in the key is safer than deleting it: a slow reader can't write an old result back.
2. The TTL covers a missed invalidation and the overdue count changing at midnight.
3. If Redis is down the endpoint falls back to the database.

## Open Questions
- Should membership changes also clear the cache, or is the TTL enough?
