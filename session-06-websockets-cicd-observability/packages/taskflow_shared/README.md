# taskflow_shared

A shared backend foundation package for TaskFlow applications and services, providing reusable infrastructure components without domain coupling.

## Overview

`taskflow_shared` encapsulates common patterns used across TaskFlow services:
- **`config`**: Base application configuration abstractions (`BaseAppSettings`).
- **`errors`**: Domain and application error hierarchy (`AppError`, `NotFoundError`, `ConflictError`, `ValidationAppError`, `UnauthorizedError`, `ForbiddenError`, `DomainError`), FastAPI exception handler registration, and retry classification for background jobs (`TransientError`, `PermanentError`).
- **`pagination`**: Standard request parameters (`PaginationParams`) and generic response envelopes (`PaginatedResponse[T]`).
- **`logging`**: ContextVar-based request ID tracing (`get_request_id`, `set_request_id`), FastAPI middleware (`RequestIdMiddleware`), and logger filters (`RequestIdFilter`).
- **`contracts`**: Base Pydantic models (`BaseSchema`, `TimestampedSchema`) and HTTP header constants (`X-Request-ID`, `X-Workspace-ID`).
- **`enums`**: Cross-domain shared enums (`Environment`, `SortOrder`).
- **`locks`**: Redis distributed lock (`distributed_lock`, `acquire_redis_lock`, `release_redis_lock`, `renew_redis_lock`): `SET NX EX`, token-checked Lua release, and renewal while held.
- **`concurrency`**: `run_async` runs a coroutine from synchronous code (such as a Celery task), also when an event loop is already running.

---

## Installation

### Local Workspace Dependency (Recommended for Monorepos)
In your project's `pyproject.toml`:

```toml
dependencies = [
    "taskflow-shared",
]

[tool.uv.sources]
taskflow-shared = { path = "packages/taskflow_shared", editable = true }
```

Install using `uv`:
```bash
uv sync
```

---

## Usage Examples

### 1. Error Handling & Standard Envelopes
```python
from fastapi import FastAPI
from taskflow_shared.errors import (
    AppError,
    NotFoundError,
    DomainError,
    register_exception_handlers,
)

app = FastAPI()
register_exception_handlers(app)

@app.get("/items/{item_id}")
async def get_item(item_id: int):
    if item_id <= 0:
        raise DomainError("Item ID must be positive")
    if item_id == 404:
        raise NotFoundError("Item not found", details=[{"field": "item_id", "message": "Does not exist"}])
    return {"id": item_id, "name": "Sample Item"}
```

All errors are returned in standard ADR-001 format:
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Item not found",
    "details": [
      {
        "field": "item_id",
        "message": "Does not exist"
      }
    ]
  }
}
```

### 2. Generic Pagination
```python
from fastapi import Depends
from taskflow_shared.pagination import PaginationParams, PaginatedResponse
from pydantic import BaseModel

class Item(BaseModel):
    id: int
    name: str

@app.get("/items", response_model=PaginatedResponse[Item])
async def list_items(params: PaginationParams = Depends()):
    # params.offset -> (page - 1) * page_size
    # params.limit -> page_size
    raw_items = [{"id": 1, "name": "Item 1"}]
    total_count = 100
    return PaginatedResponse[Item].create(
        items=raw_items,
        total=total_count,
        page=params.page,
        page_size=params.page_size,
    )
```

### 3. Request Tracing Middleware
```python
from fastapi import FastAPI
from taskflow_shared.logging import RequestIdMiddleware, get_request_id

app = FastAPI()
app.add_middleware(RequestIdMiddleware)

@app.get("/status")
async def status():
    current_request_id = get_request_id()
    return {"status": "ok", "request_id": current_request_id}
```
The middleware:
1. Captures `X-Request-ID` from inbound request headers (or generates a new UUID4).
2. Sets it in the execution context via Python's `contextvars`.
3. Injects `X-Request-ID` into the outbound HTTP response headers.

### 4. Distributed Lock
```python
from redis.asyncio import Redis
from taskflow_shared.locks import distributed_lock

async def nightly_job(redis: Redis) -> None:
    async with distributed_lock(redis, "locks:nightly-job", timeout_seconds=300) as token:
        if token is None:
            return  # another run holds the lock
        ...  # the lock is renewed every timeout_seconds / 3 until the block exits
```
The caller owns the Redis client. The lock is released only by the holder whose token
still matches, so an expired holder can never delete the next holder's lock.

### 5. Background Job Helpers
```python
from taskflow_shared.concurrency import run_async
from taskflow_shared.errors import PermanentError, TransientError

class MailerDown(TransientError): ...       # retry with backoff
class RecipientMissing(PermanentError): ...  # fail at once

def celery_task_body(job_id: int) -> dict:
    return run_async(process(job_id))  # sync Celery task, async logic
```

---

## Architectural Boundaries (What NOT to put here)
- **NO database ORM models or connections** (SQLAlchemy, Alembic).
- **NO business/domain entities** (`User`, `Task`, `Project`).
- **NO app-specific workflow transitions**.

Keep `taskflow_shared` lean, focused, and independently testable.
