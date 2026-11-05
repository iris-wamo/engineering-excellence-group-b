# Session 05 — Research & Reading Discussion

## Overview
Reading questions for Session 05, by topic. The tradeoffs we actually hit while building
them, and the questions still open, are collected in
[`end-to-end-flow.md` §4](end-to-end-flow.md#4-open-tradeoffs-and-questions); each topic doc
answers its own questions in detail.

## Discussion Questions by Topic
- **Async programming**: What does async improve? Concurrency vs parallelism? Blocking I/O inside async? When to use Celery instead?
- **Redis caching**: When is caching useful? Stale cache risks? TTL vs invalidation? What should not be cached?
- **Pub/Sub vs Streams**: Why can Pub/Sub lose messages? What makes Streams durable? Consumer groups and acknowledgments? Idempotency requirement?
- **Celery retries**: Retryable vs non-retryable failures? Worker or broker down behavior? Duplicate side effects?
- **Celery Beat**: Worker vs Beat difference? Periodic jobs criteria? Schedule overlap handling?
- **Flower monitoring**: What Flower shows vs application logs? Missing observability?
