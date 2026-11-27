# Session 06 — SLOs & Deliverables

## Overview
Placeholder for Session 06 objectives, targets and measured results. Targets are teaching targets, not claimed system performance; record observed results separately.

## Topics Covered
- Real-time notification latency (p95 from commit to event arrival)
- Authorization correctness for WebSocket connections and subscriptions
- CI quality enforcement and pipeline run duration
- API p95 latency and error rate under controlled load
- Incident detectability and time to detection
- Recovery and data integrity after reconnect or restore

## API health and latency (#126)

Target set before measuring. It is a teaching target for a local stack, not a production claim.

| | Value |
|---|---|
| Endpoint | `GET /api/v1/projects` (anonymous, Workspace 1) |
| Target | p95 ≤ 200 ms and error rate (5xx or failed requests) ≤ 1% |
| Workload | 20 concurrent clients, back to back, for 60 s (`make load-test`, `scripts/load_test.py`) |
| Environment | Local Docker stack on a MacBook (api: one uvicorn process with `--reload`) |
| Date | 2026-11-15 |

Observed:

| Source | Requests | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| Client (`make load-test`) | 25,236 (420.6/s) | 41.4 ms | **81.1 ms** | 169.6 ms | **0 (0.00%)** |
| Server (Prometheus, `taskflow_http_request_duration_seconds`) | | | 96.2 ms | | 0 5xx |

Result: **target met**. The server p95 is an estimate within histogram buckets (50–100 ms here),
so it is coarser than the client figure. The p99 at about 2× p95 is worth watching if the
workload grows.
