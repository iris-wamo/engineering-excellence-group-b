# Celery Flower Monitoring & Observability

Issue **#102**. As background processing scales with asynchronous jobs (#101) and scheduled periodic tasks (#102),
inspecting terminal stdout logs becomes inefficient for operational oversight.
TaskFlow integrates **Flower**—a real-time, web-based monitoring and administration dashboard for Celery.

---

## 1. What Flower Monitors

Flower connects to the Celery broker (Redis) and subscribes to Celery worker event streams:

| Feature | What Flower Shows | Operational Value |
| :--- | :--- | :--- |
| **Worker Health** | Online / offline status, pool size, active concurrency, load average | Detect dead worker pods or stalled worker processes immediately |
| **Task History** | Succeeded, failed, retried, and active jobs with UUIDs, runtime, and args | Pinpoint failing tasks, inspect stack traces, and track execution latency |
| **Beat Schedules** | Registered periodic tasks, intervals, last run timestamps | Verify periodic jobs (like due-task reminders) are registered and ticking |
| **Queue Depths** | Current message counts in Redis broker lists (`celery`) | Detect broker queue backpressure and scaling bottlenecks |

---

## 2. Dashboards vs Application Logs

Understanding the division of responsibility between Flower and application logging is critical:

### What to Check in Flower:
- **System-level throughput**: Are workers processing tasks within expected SLOs (< 500ms)?
- **Error spikes**: Are retry rates surging due to a database blip or downstream outage?
- **Broker backpressure**: Is the `celery` queue growing faster than workers can consume?
- **Worker pool capacity**: Are all worker slots saturated?

### What to Check in Application Logs (`structlog` / PostgreSQL):
- **Business payload semantics**: Exact IDs, customer notifications, and tenancy metadata.
- **SQL / ORM query logs**: Lock acquisition timings, transaction commits, and rollbacks.
- **Audit trails**: Activity logs and security events (`TASK_ASSIGNED`, `TASK_DUE_REMINDER`).
- **Distributed lock debug logs**: Overlapping run prevention events and lock token releases.

---

## 3. Running Flower in TaskFlow

### Via Docker Compose
Flower is configured as a dedicated container service in `compose.yaml`:

```yaml
  flower:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    entrypoint: []  # only the api service runs migrations
    command: ["celery", "-A", "app.core.celery_app", "flower", "--port=5555"]
    ports:
      - "127.0.0.1:5555:5555"
    environment:
      DATABASE_URL: postgresql+asyncpg://...@db:5432/taskflow  # required by app Settings
      MONGO_URL: mongodb://mongo:27017
      MONGO_DB: taskflow
      REDIS_URL: redis://redis:6379/0
      CELERY_BROKER_URL: redis://redis:6379/1
      CELERY_RESULT_BACKEND: redis://redis:6379/2
      FLOWER_BASIC_AUTH: ${FLOWER_BASIC_AUTH:-taskflow:taskflow}
    depends_on:
      redis:
        condition: service_healthy
```

- **Settings**: `-A app.core.celery_app` imports the app `Settings`, which require `DATABASE_URL`, `MONGO_URL`, and `MONGO_DB` even though Flower only talks to Redis. Without them the container fails at startup with a pydantic `Field required` error.
- **Access**: Flower can revoke and terminate tasks and shows task arguments, so it is published on the host loopback only and protected by basic auth. Set `FLOWER_BASIC_AUTH=user:password` in your shell or `.env` to override the dev default `taskflow:taskflow`.

Start the containerized stack:
```bash
docker compose up -d flower
```

### Via Local Makefile Target
To run Flower locally against the Docker Redis broker:
```bash
make flower
```
Flower starts at **`http://127.0.0.1:5555`**. The local target binds to loopback and has no auth.

---

## 4. Flower Verification & API Endpoints

Flower exposes an HTTP REST API in addition to its web UI:

```bash
# Check worker status via Flower API (drop -u for the unauthenticated `make flower`)
curl -s -u taskflow:taskflow http://localhost:5555/api/workers | jq .

# Check active tasks via Flower API
curl -s -u taskflow:taskflow "http://localhost:5555/api/tasks?limit=5" | jq .
```
