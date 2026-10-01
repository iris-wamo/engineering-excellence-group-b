# Session 04 — SLOs & Deliverables

## Objectives & Focus
Session 04 focuses on codebase separation, a reusable shared backend package, domain workflows, authentication/RBAC, and raw data normalization into relational application records.

---

## Service Level Objectives (SLOs)

### 1. Separation SLO
Routes should not contain business workflow logic beyond request parsing and dispatching to services/workflows.

### 2. Shared Package SLO
Common errors, pagination models, enums, and request ID tracking helpers must not be duplicated across modules; they belong in `packages/taskflow_shared/`.

### 3. Workflow SLO
The domain workflow engine must consistently reject invalid state transitions and persist an activity/audit trail where applicable.

### 4. Auth / RBAC SLO
Protected endpoints must reject unauthenticated requests (401) and forbid roles lacking sufficient permissions (403), matching the documented authorization matrix.

### 5. Import Normalization SLO
Failed raw imports must remain traceable with descriptive error details; successful imports must cleanly produce normalized PostgreSQL records.

### 6. Testing SLO
Core workflow and RBAC rules must have comprehensive positive and negative test coverage using reusable test fixtures and factory helpers.
