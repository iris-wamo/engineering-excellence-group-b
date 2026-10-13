# Session 05 — Research & Reading Discussion

## Overview
Placeholder for Session 05 research reading questions and implementation trade-offs.

## Discussion Questions by Topic
- **Async programming**: What does async improve? Concurrency vs parallelism? Blocking I/O inside async? When to use Celery instead?
- **Redis caching**: When is caching useful? Stale cache risks? TTL vs invalidation? What should not be cached?
- **Pub/Sub vs Streams**: Why can Pub/Sub lose messages? What makes Streams durable? Consumer groups and acknowledgments? Idempotency requirement?
- **Celery retries**: Retryable vs non-retryable failures? Worker or broker down behavior? Duplicate side effects?
- **Celery Beat**: Worker vs Beat difference? Periodic jobs criteria? Schedule overlap handling?
- **Flower monitoring**: What Flower shows vs application logs? Missing observability?
