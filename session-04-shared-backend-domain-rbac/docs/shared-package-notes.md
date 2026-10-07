# Shared Package Notes (`taskflow_shared`)

## Overview
`taskflow_shared` is a standalone, reusable backend package located in `packages/taskflow_shared/`. It is installed as an editable dependency in `session-04-shared-backend-domain-rbac/` using `uv`.

## Scope & Purpose
The shared backend package provides foundational, cross-cutting infrastructure across TaskFlow services without creating tight coupling to domain-specific entities.

---

## Included Modules & Capabilities

### 1. `config` (`taskflow_shared.config`)
- **`BaseAppSettings`**: Base Pydantic Settings class with environment detection (`DEVELOPMENT`, `TESTING`, `STAGING`, `PRODUCTION`), `.env` loading, and common application metadata.

### 2. `errors` (`taskflow_shared.errors`)
- **Exception Hierarchy**: Canonical base `AppError` and standard subclasses:
  - `NotFoundError` (HTTP 404)
  - `ConflictError` (HTTP 409)
  - `ValidationAppError` (HTTP 422)
  - `UnauthorizedError` (HTTP 401) — for auth issues (#70)
  - `ForbiddenError` (HTTP 403) — for RBAC permission checks (#71)
  - `DomainError` (HTTP 422) — for business workflow violations (#69)
- **Response Schemas (ADR-001)**:
  - `ErrorDetail(field, message)`: Maps Pydantic error loc to dotted path (e.g. `items.0.name`) for nested payload error tracing.
  - `ErrorBody(code, message, details)`: Canonical code (e.g. `VALIDATION_ERROR`, `NOT_FOUND`) with clear summary message (`"Request validation failed"` for 422).
  - `ErrorResponse(error: ErrorBody)`
- **Exception Handlers**:
  - `register_exception_handlers(app: FastAPI)`: Intercepts `AppError`, `RequestValidationError`, `StarletteHTTPException` (catching both Starlette 404/405 routing errors and FastAPI `HTTPException`), and unhandled `Exception`, ensuring all error payloads adhere strictly to the shared envelope while preserving HTTP headers (e.g., `WWW-Authenticate`, `Allow`, `X-Request-ID`).

### 3. `pagination` (`taskflow_shared.pagination`)
- **`PaginationParams`**: Reusable query parameter dependency (`page: int = 1`, `page_size: int = 20`, max 100) with automatic `.offset` and `.limit` properties.
- **`PaginatedResponse[T]`**: Generic envelope holding `items: list[T]`, `total: int`, `page: int`, `page_size: int`, and dynamic `@computed_field` property `total_pages: int`.

### 4. `logging` (`taskflow_shared.logging`)
- **`RequestIdMiddleware`**: ASGI middleware that preserves an incoming `X-Request-ID` or generates a unique UUID4, sets it in a `contextvars` variable, and propagates it in the response header.
- **`get_request_id()` / `set_request_id()`**: Context helpers accessible anywhere in the call stack.
- **`RequestIdFilter`**: Logging filter to inject `request_id` into formatted log records.

### 5. `contracts` (`taskflow_shared.contracts`)
- **`BaseSchema`**: Base Pydantic model with `ConfigDict(from_attributes=True)`.
- **`TimestampedSchema`**: Base schema including `created_at` and `updated_at`.
- **Constants**: `HEADER_REQUEST_ID`, `HEADER_WORKSPACE_ID`, `HEADER_CORRELATION_ID`.

### 6. `enums` (`taskflow_shared.enums`)
- **`Environment`**: Standard StrEnum for environment profiles.
- **`SortOrder`**: Standard StrEnum for sorting directions (`asc`, `desc`).

---

## Architectural Boundaries (Strict Separation)

### What BELONGS in `taskflow_shared`:
- Reusable, domain-agnostic helpers (pagination, request tracking, error envelopes).
- Infrastructure protocols, interfaces, and base configuration.
- Generic HTTP constants and response formats.

### What DOES NOT belong in `taskflow_shared`:
- **Domain entities & models**: `User`, `Task`, `Project`, `Workspace` models belong in `app/models/`.
- **Database engines & sessions**: SQLAlchemy async engines, sessionmakers, and Alembic migrations belong in `app/core/db.py` and `alembic/`.
- **Domain state machines**: Workflow rules (e.g. `todo → in_progress → review → done`) belong in `app/workflows/`.
- **Authentication logic**: Password hashing, JWT signing, and OAuth tokens belong in `app/auth/`.

---

## Downstream Team Integration
- **#69 (Task Status Workflow)**: Raise `DomainError("Cannot transition from {current} to {target}")` which is automatically formatted into 422 JSON envelopes.
- **#70 & #71 (Auth & RBAC)**: Raise `UnauthorizedError` and `ForbiddenError` for unauthenticated or unauthorized operations.
- **#72 (Multi-tenancy Workspaces)**: Use `HEADER_WORKSPACE_ID` from `taskflow_shared.contracts` to extract and validate workspace context.
- **#73 (Raw Import Normalization)**: Use `PaginatedResponse` and `taskflow_shared.logging` for traceability across import batches.
- **#74 (Test Helpers)**: Build on `taskflow_shared` models and error assertions.
