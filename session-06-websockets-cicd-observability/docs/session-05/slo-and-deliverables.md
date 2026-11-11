# Session 05 — SLOs & Deliverables

## Overview
Session 05 moves TaskFlow from a request/response API to an asynchronous backend. The end-to-end
flow that ties the pieces together is described in [`end-to-end-flow.md`](end-to-end-flow.md).

## Targets observed in the end-to-end demo

| Path | Target | Observed (`make flow-demo`, 3 runs) |
|------|--------|-----------------------------|
| Assign / status change API response | Does not wait on any side effect | 15–32 ms |
| Assignment notification delivered | Within seconds while a worker is online. After a failed publish (broker down), by the outbox sweep: at most 10 min after the failed publish or 5 min after the broker is back, whichever is later | ~1 s |
| Due-task reminder | Within one Beat interval (60 s) of a task becoming due | 25–47 s |
| Cached summary staleness | At most the TTL (30 s) if an invalidation is lost; otherwise invalidated on every write | Invalidated on each write |

## Expected PR Deliverables

| Deliverable | Evidence |
|-------------|----------|
| FastAPI async implementation or blocking-vs-non-blocking comparison | [`async-programming.md`](async-programming.md), [Demo 01](../../demos/session-05/01-async-api/demo.md) |
| Redis added to Docker Compose | `redis` service in [`compose.yaml`](../../compose.yaml) |
| Redis caching use case with cache hit/miss/invalidation evidence | [`redis-caching.md`](redis-caching.md), [Demo 02](../../demos/session-05/02-redis-caching/demo.md) |
| Redis Pub/Sub or Streams use case with delivery behavior explained | [`redis-pubsub-vs-streams.md`](redis-pubsub-vs-streams.md), [Demo 03](../../demos/session-05/03-redis-pubsub-streams/demo.md) |
| Celery worker setup with at least one retryable task | [`celery-jobs.md`](celery-jobs.md), [Demo 04](../../demos/session-05/04-celery-jobs/demo.md) |
| Celery Beat setup with at least one periodic task | [`celery-beat.md`](celery-beat.md), [Demo 05](../../demos/session-05/05-celery-beat/demo.md) |
| Flower setup with monitoring evidence | [`flower-monitoring.md`](flower-monitoring.md), [Demo 06](../../demos/session-05/06-flower-monitoring/demo.md) |
| One connected flow across all of the above | [`end-to-end-flow.md`](end-to-end-flow.md), [Demo 07](../../demos/session-05/07-end-to-end-flow/demo.md) |
| Failure cases tested and explained | [`end-to-end-flow.md` §3](end-to-end-flow.md#3-failure-cases-tested) |
| Updated README / run instructions | [README → Full-stack walkthrough](../../README.md#full-stack-walkthrough) |
| Loom links from group demos | The `Loom Video` section of each `demos/session-05/*/demo.md` |
| Tradeoffs and open questions documented in PR | [`end-to-end-flow.md` §4](end-to-end-flow.md#4-open-tradeoffs-and-questions) |
