# Architecture Boundaries & Ownership

## Overview
This document defines boundary and ownership guidelines across the TaskFlow codebase layers:
- Shared Package (`packages/taskflow_shared/`)
- API / Routes Layer (`app/api/`)
- Auth Layer (`app/auth/`)
- Service Layer (`app/services/`)
- Repository Layer (`app/repositories/`)
- Workflows Layer (`app/workflows/`)
- Data & Models Layer (`app/models/`, `app/schemas/`, `app/db/`)

---

## Layer Responsibilities & Constraints

### 1. Shared Package (`packages/taskflow_shared`)
- **Belongs here:** Reusable utilities across services (logging, pagination models, base exception classes, common enums/contracts).
- **Does NOT belong here:** Business rules, entity-specific database models, domain logic, application state.

### 2. API / Routes Layer (`app/api`)
- **Belongs here:** HTTP endpoint declarations, request deserialization, dependency injection, status code mappings.
- **Rule:** Routes must NOT contain domain workflow logic beyond request parsing and dispatching to services/workflows.

### 3. Auth Layer (`app/auth`)
- **Belongs here:** JWT creation and validation, password hashing, authentication dependencies (`get_current_user`), and RBAC permission checks.

### 4. Service Layer (`app/services`)
- **Belongs here:** Application use cases, coordination between repositories, transactions, business logic orchestration.

### 5. Repository Layer (`app/repositories`)
- **Belongs here:** Data access logic, SQLAlchemy queries, database persistence abstraction.

### 6. Workflow Layer (`app/workflows`)
- **Belongs here:** State transition machines, domain policy engines, business validation engines, audit trail generation.

---

## Dependency Direction
`API` → `Auth / Services / Workflows` → `Repositories` → `Models / DB`
All layers may consume `taskflow_shared`.
