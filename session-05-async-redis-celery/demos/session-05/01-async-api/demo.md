# Demo 01 — Async Programming in FastAPI (Blocking vs Non-Blocking)

## Loom Video
- **Loom Video Status**: **MANUAL FOLLOW-UP REQUIRED** (No Loom recording exists in the repository. A video link was not invented; record a 2–3 minute walkthrough and paste the URL here).
- **Loom Link**: `[Manual Follow-up: Insert Loom recording URL here once recorded]`
- **Recording Instructions**: Record a 2–3 minute walkthrough demonstrating:
  1. The task summary endpoint returning the 4 required pieces of data.
  2. Executing `uv run python scripts/demo_async_vs_blocking.py` to highlight the side-by-side concurrency timing table (7.63x speedup).
  3. The simulated timeout case triggering an HTTP 504 Gateway Timeout with the standard ADR-001 error response envelope.

---

## Objective
Demonstrate the concrete engineering impact of asynchronous programming in FastAPI:
1. Show how non-blocking I/O multiplexing (`asyncio.sleep`) allows multiple concurrent requests to overlap on a single thread.
2. Demonstrate how synchronous blocking operations (`time.sleep`) cause event loop starvation and head-of-line blocking.
3. Verify that external call timeouts prevent hung dependencies from starving application resources by returning a standard HTTP 504 error response envelope.

---

## Scenario
A project dashboard calls a `GET /api/v1/tasks/summary` endpoint to display task metrics (status breakdown, overdue count, assigned count) combined with health telemetry from a simulated external metrics microservice. We compare how the API behaves when multiple team members load their dashboards simultaneously under non-blocking async vs synchronous blocking execution.

---

## Commands / Steps Used

```bash
# 1. Run integration tests (normal summary, blocking summary, timeouts, workspace isolation, concurrency)
uv run pytest tests/integration/api/test_task_summary_api.py -v

# 2. Run unit tests for Pydantic schemas
uv run pytest tests/unit/schemas/test_task_summary_schema.py -v

# 3. Execute the automated benchmark and demonstration script
uv run python scripts/demo_async_vs_blocking.py --concurrency 10 --delay 0.2 --timeout 1.0

# 4. Direct curl test — Normal async summary
curl -s -X GET "http://localhost:8000/api/v1/tasks/summary?external_delay=0.2&external_timeout=1.0" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Workspace-ID: 1" | jq .

# 5. Direct curl test — External timeout trigger
curl -s -X GET "http://localhost:8000/api/v1/tasks/summary?external_delay=1.5&external_timeout=0.5" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "X-Workspace-ID: 1" | jq .
```

---

## Expected Behavior
1. **Async Endpoint (`/tasks/summary`)**:
   Under 10 concurrent requests with 0.2s external delay, all requests should overlap on the asyncio event loop and complete in $\approx 0.2\text{s} - 0.3\text{s}$ total.
2. **Blocking Endpoint (`/tasks/summary/blocking`)**:
   Under 10 concurrent requests with 0.2s external delay, `time.sleep` blocks the event loop thread, serializing requests to $\approx 10 \times 0.2\text{s} = 2.0\text{s}$ total.
3. **Timeout Case**:
   When external delay exceeds the timeout threshold (e.g. 1.2s delay vs 0.5s timeout), the API should abort at the 0.5s deadline and return HTTP 504 with code `EXTERNAL_SERVICE_TIMEOUT`.

---

## Actual Findings

Execution of `scripts/demo_async_vs_blocking.py`:

```
===========================================================================
 SIDE-BY-SIDE PERFORMANCE COMPARISON SUMMARY
===========================================================================
Endpoint                           | Requests | Total Time   | Avg Latency
-----------------------------------+----------+--------------+-------------
GET /api/v1/tasks/summary (Async)  | 10       |     0.276s  |     0.261s
GET /tasks/summary/blocking (Sync) | 10       |     2.106s  |     1.576s
---------------------------------------------------------------------------
Concurrency Speedup: 7.63x faster with non-blocking async!
```

---

## Evidence

### 1. Successful Task Summary Response (HTTP 200 OK)
All four required pieces of data returned:
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

### 2. External Call Timeout Error Response (HTTP 504 Gateway Timeout)
Enforced in 0.520s against a 1.2s delay:
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

### 3. Automated Test Suite Output
```
tests/integration/api/test_task_summary_api.py::test_async_task_summary_success_with_all_four_pieces_of_data PASSED
tests/integration/api/test_task_summary_api.py::test_blocking_task_summary_success_matches_structure PASSED
tests/integration/api/test_task_summary_api.py::test_async_summary_external_call_timeout_returns_504 PASSED
tests/integration/api/test_task_summary_api.py::test_blocking_summary_external_call_timeout_returns_504 PASSED
tests/integration/api/test_task_summary_api.py::test_summary_workspace_isolation PASSED
tests/integration/api/test_task_summary_api.py::test_summary_empty_workspace_returns_zero_counts PASSED
tests/integration/api/test_task_summary_api.py::test_async_summary_concurrency_non_blocking_behavior PASSED
tests/integration/api/test_task_summary_api.py::test_task_summary_due_date_boundary_conditions PASSED
tests/integration/api/test_task_summary_api.py::test_task_summary_query_parameter_validation PASSED
============================== 9 passed in 1.04s ===============================
```

---

## What We Learned
1. **Async allows cooperative I/O multiplexing**: When operations yield via `await asyncio.sleep()`, the server handles concurrent requests on a single thread without CPU contention.
2. **Blocking code in `async def` is fatal**: A single `time.sleep()` call or blocking library call freezes the entire worker process, creating head-of-line blocking for all subsequent requests.
3. **Timeouts are critical fault barriers**: Without strict timeouts (`asyncio.wait_for`), slow downstream services cause connection pools to deplete and cascade failures back to the client.
4. **Where async is NOT enough**: CPU-heavy tasks or long-running workflows (> 2-3s) cannot run safely inside API coroutines; they must be offloaded to Celery background workers.

---

## Open Questions
1. **Caching (Issue #99)**: Should summary metrics be cached in Redis with a short TTL (e.g. 15–30s) or invalidated on task mutations (`create`, `status`, `assign`)?
2. **Background Jobs (Issue #101)**: Should long-running data exports and batch reports be processed via Celery task queues instead of synchronous/asynchronous HTTP endpoints?
