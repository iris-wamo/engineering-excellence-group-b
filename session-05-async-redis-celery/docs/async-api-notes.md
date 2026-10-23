# TaskFlow Session 05 — Async Task Summary API Notes

## 1. Overview & Endpoints

This document details the implementation, configuration, and observed performance benchmarks for the TaskFlow **Task Summary API** introduced in Session 05 (Issue #98).

The API provides two endpoints:
- `GET /api/v1/tasks/summary`: Non-blocking asynchronous implementation using cooperative `asyncio` concurrency and external timeout protection.
- `GET /api/v1/tasks/summary/blocking`: Synchronous blocking simulation offloaded to a bounded thread pool (`ThreadPoolExecutor(max_workers=4)`) via `loop.run_in_executor` to keep the event loop responsive. (Note: pure event-loop starvation from an accidental synchronous call directly inside `async def` is tested and demonstrated in `test_sync_call_inside_async_starves_event_loop`).

Both endpoints enforce multi-tenant workspace isolation and return identical response schemas.

---

## 2. API Reference & Parameters

### Headers
| Header | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `Authorization` | String | No* | Bearer JWT token (`Bearer <token>`). Required if non-default workspace is requested. |
| `X-Workspace-ID` | Integer | No | Active workspace ID (defaults to `1` when omitted). |

### Query Parameters
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `external_delay` | float | `0.2` | Simulated latency of the external dependency in seconds ($0.0 \le \text{delay} \le 10.0$). |
| `external_timeout` | float | `1.0` | Maximum allowable wait time before failing with HTTP 504 ($\text{timeout} > 0.0$). |

---

## 3. Response Schemas

### A. Successful Response (HTTP 200 OK)
The summary returns all four required metrics in a single aggregated payload:
1. `counts_by_status`: Object containing task counts for every supported status (`todo`, `in_progress`, `review`, `done`).
2. `overdue_count`: Number of tasks whose `due_date < today` and whose status is not `done`.
3. `assigned_count`: Number of tasks with a non-null `assignee_id`.
4. `external_service`: Metadata from the simulated external dependency.

```json
{
  "workspace_id": 1,
  "counts_by_status": {
    "todo": 4,
    "in_progress": 8,
    "review": 0,
    "done": 0
  },
  "overdue_count": 4,
  "assigned_count": 12,
  "total_count": 12,
  "external_service": {
    "service": "workload_service",
    "status": "healthy",
    "latency_ms": 201.1,
    "mode": "async"
  }
}
```

### B. Timeout Response (HTTP 504 Gateway Timeout)
When `external_delay > external_timeout`, the request fails with the standard TaskFlow ADR-001 error response envelope:

```json
{
  "error": {
    "code": "EXTERNAL_SERVICE_TIMEOUT",
    "message": "External service timed out",
    "details": [
      {
        "field": "external_call",
        "message": "Call exceeded the configured timeout of 0.5s"
      }
    ]
  }
}
```

### C. Timeout Behavior & Limitations
- **Simulated Sleeps vs. Real HTTP Clients**: In our endpoints, `await asyncio.sleep(delay)` models non-blocking network wait, and `time.sleep(delay)` models uncooperative blocking wait. In production, a real asynchronous client (`httpx.AsyncClient`) registers sockets with the event loop so the thread never blocks, whereas a real synchronous client (`requests.get`) blocks the OS thread during socket operations for up to its configured timeout.
- **Non-blocking coroutines (`asyncio.wait_for`)**: When `asyncio.wait_for(asyncio.sleep(delay), timeout=timeout)` fires, asyncio cancels the underlying task and raises `TimeoutError`. The handler catches this and returns HTTP 504 immediately upon reaching the deadline.
- **Synchronous blocking operations (`time.sleep`)**: `asyncio.wait_for` **cannot** cancel or interrupt synchronous blocking code. Because `time.sleep` blocks the OS thread running the event loop, asyncio's timer cannot tick until `time.sleep` returns. In our blocking demonstration, we simulate the socket timeout of a synchronous HTTP client (e.g. `requests.get(url, timeout=0.5)`) by sleeping for the `timeout` duration and then raising `ExternalServiceTimeoutError`.

---

## 4. Performance Benchmark: Async vs. Blocking

### Test Environment
- **OS**: macOS (Apple Silicon Darwin arm64)
- **Runtime**: Python 3.12.12 (managed via `uv`)
- **Web Framework**: FastAPI 0.139.0 / Starlette 0.46
- **Database**: PostgreSQL 16 (via `asyncpg` 0.31.0 and SQLAlchemy 2.0.51)
- **Concurrency Tool**: In-process ASGI testing via `httpx.AsyncClient` with `asyncio.gather`

### Benchmark Execution
Executed using [`scripts/demo_async_vs_blocking.py`](../scripts/demo_async_vs_blocking.py) with 10 concurrent requests and 0.20s external delay:

```
===========================================================================
 SIDE-BY-SIDE PERFORMANCE COMPARISON SUMMARY
===========================================================================
Endpoint                           | Requests | Total Time   | Avg Latency 
-----------------------------------+----------+--------------+-------------
GET /api/v1/tasks/summary (Async)  | 10       |     0.268s  |     0.255s
GET /tasks/summary/blocking (Sync) | 10       |     0.653s  |     0.403s
---------------------------------------------------------------------------
Concurrency Speedup: 2.43x faster with non-blocking async!
```

### Engineering Findings
1. **Why Async Succeeded**:
   During `await asyncio.sleep(0.2)`, each request yielded execution back to the event loop. All 10 requests waited concurrently on their simulated network I/O, completing in approximately 0.27s total.
2. **Why Blocking Endpoint Took Longer**:
   In `/tasks/summary/blocking`, the external call is offloaded to a bounded thread pool (`ThreadPoolExecutor(max_workers=4)`). Because the pool is limited to 4 workers, 10 concurrent requests cannot all run at once and must process in batches ($4 + 4 + 2$), taking 0.653s total (2.43x speedup for async).
   *Note*: Pure event-loop starvation occurs when synchronous blocking code (like `time.sleep`) runs directly on the event loop thread without thread offloading. This failure mode is explicitly tested in `test_sync_call_inside_async_starves_event_loop` in `tests/integration/api/test_task_summary_api.py`, where $N=3$ requests serialize to $\ge 0.3\text{s}$.

---

## 5. Database Connection Management

In SQLAlchemy `AsyncSession`, connection checkout is lazy: the physical connection is checked out from the connection pool only when the first SQL statement is executed.

To manage database connections safely during the summary endpoint:
- In `TaskService.get_task_summary()` and `TaskService.get_task_summary_blocking()`, the simulated external call runs **before** `TaskRepository.get_summary_metrics(db, ...)`.
- As a result, the summary query does not hold a database connection while waiting for the simulated external service.
- If the external dependency times out, zero database connections are ever checked out by the summary service.
- When the external call succeeds, the database connection is acquired for only $\approx 1\text{ms}$ to execute the single SQL `CASE` aggregate query before being returned to the pool upon route completion.
- *Note*: This applies specifically to the summary endpoint's sequencing; endpoints that query the database before performing external I/O would hold their checked-out connections unless explicitly committed, closed, or restructured.

---

## 6. Architectural Boundaries: Where Async is Not Enough

While asynchronous endpoints optimize I/O concurrency on the web tier, they are not a universal solution:
- **CPU-Bound Work**: Synchronous CPU-heavy code inside async handlers prevents the event loop from serving other coroutines until that code finishes or yields. CPU-bound work cannot be accelerated by async and requires a process pool (`ProcessPoolExecutor`) or background worker.
- **Long-Running Work**: Any operation taking longer than standard HTTP timeouts (> 2–3s) risks connection termination by proxies and load balancers.
- **Reliability & Retries**: Asynchronous web tasks do not survive worker restarts. Operations requiring durable retries or background processing should be delegated to **Celery workers backed by Redis** (Issue #101).

---

## 7. How to Run Tests & Benchmarks

```bash
# 1. Run unit tests for schemas
uv run pytest tests/unit/schemas/test_task_summary_schema.py -v

# 2. Run integration tests (includes timeout, boundary conditions, and workspace isolation)
uv run pytest tests/integration/api/test_task_summary_api.py -v

# 3. Run the performance benchmark demonstration script
uv run python scripts/demo_async_vs_blocking.py --concurrency 10 --delay 0.2 --timeout 1.0
```
