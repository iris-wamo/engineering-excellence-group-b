# Session 03 — SLOs and Deliverables

This document defines the Service Level Objectives (SLOs) and key engineering deliverables for Session 03 (Database Correctness, Transactions, Migrations, and Query Performance).

---

## 1. Seed Data Reproducibility SLO

### Objective
Ensure that every developer and reviewer can generate a known, deterministic, and repeatable database state across small and large dataset volumes without embedding demo data into Alembic schema migrations.

### Target Specifications
- **Clean Reset Path**: `make db-reset` or `scripts/seed_data.py --reset` must truncate all user, project, project_user, and task tables cleanly without schema drop/re-create overhead.
- **Data Volume Presets**:
  - **Standard Local Dev (`make seed`)**: Generates ~10 users, 5 projects, and 200 tasks in < 1 second.
  - **Query Performance Benchmarking (`make seed-large`)**: Generates 100 users, 25 projects, and 10,000 tasks in < 3 seconds.
- **Isolation from Migrations**: Database migrations define schema structure only. Data seeding is completely decoupled in `scripts/seed_data.py`.

### Seeding Execution Results

#### Standard Local Dev Seed (`make seed`)
```text
$ make seed
uv run python scripts/seed_data.py --reset
Starting seed process (Target: 10 users, 5 projects, 200 tasks)...
Clearing existing data...
Database truncated successfully.
Seeding 10 users...
Seeding 5 projects...
Seeding project memberships...
Seeding 200 tasks (batch size: 1000)...
  Inserted tasks 1 to 200...

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 0.11 seconds
--------------------------------------------------
Table Name           | Row Count
--------------------------------------------------
user                 | 10
project              | 5
project_user         | 23
task                 | 200
==================================================
```

#### Query Performance Benchmarking (`make seed-large`)
```text
$ make seed-large
uv run python scripts/seed_data.py --reset --tasks 10000 --users 100 --projects 25
Starting seed process (Target: 100 users, 25 projects, 10000 tasks)...
Clearing existing data...
Database truncated successfully.
Seeding 100 users...
Seeding 25 projects...
Seeding project memberships...
Seeding 10000 tasks (batch size: 1000)...
  Inserted tasks 1 to 1000...
  Inserted tasks 1001 to 2000...
  Inserted tasks 2001 to 3000...
  Inserted tasks 3001 to 4000...
  Inserted tasks 4001 to 5000...
  Inserted tasks 5001 to 6000...
  Inserted tasks 6001 to 7000...
  Inserted tasks 7001 to 8000...
  Inserted tasks 8001 to 9000...
  Inserted tasks 9001 to 10000...

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 1.08 seconds
--------------------------------------------------
Table Name           | Row Count
--------------------------------------------------
user                 | 100
project              | 25
project_user         | 786
task                 | 10000
==================================================
```

#### Stress Testing Dataset (`make seed-huge`)
```text
$ make seed-huge
uv run python scripts/seed_data.py --reset --tasks 50000 --users 200 --projects 50
Starting seed process (Target: 200 users, 50 projects, 50000 tasks)...
Clearing existing data...
Database truncated successfully.
Seeding 200 users...
Seeding 50 projects...
Seeding project memberships...
Seeding 50000 tasks (batch size: 1000)...
  Inserted tasks 1 to 1000...
  ...
  Inserted tasks 49001 to 50000...

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 5.01 seconds
--------------------------------------------------
Table Name           | Row Count
--------------------------------------------------
user                 | 200
project              | 50
project_user         | 2699
task                 | 50000
==================================================
```

#### Database Reset & Re-Seed (`make db-reset`)
```text
$ make db-reset
uv run python scripts/seed_data.py --reset
Starting seed process (Target: 10 users, 5 projects, 200 tasks)...
Clearing existing data...
Database truncated successfully.
Seeding 10 users...
Seeding 5 projects...
Seeding project memberships...
Seeding 200 tasks (batch size: 1000)...
  Inserted tasks 1 to 200...

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 0.11 seconds
--------------------------------------------------
Table Name           | Row Count
--------------------------------------------------
user                 | 10
project              | 5
project_user         | 23
task                 | 200
==================================================
```

#### Empty Database / Row Truncation (`make db-clean`)
```text
$ make db-clean
uv run python scripts/seed_data.py --clean-only
Starting clean reset process (Wiping all data)...
Clearing existing data...
Database truncated successfully.

==================================================
 SEEDING COMPLETE
==================================================
Time Taken       : 0.06 seconds
--------------------------------------------------
Table Name           | Row Count
--------------------------------------------------
user                 | 0
project              | 0
project_user         | 0
task                 | 0
==================================================
```




---

## 2. Correctness SLO (Task Assignment Transaction Safety)

### Objective
Guarantee absolute atomicity and referential consistency across multi-table business operations. When assigning or reassigning a task, all affected entities must be updated and recorded as a single business operation within a strict transaction boundary. Any failure midway through the process must trigger an immediate, full rollback resulting in zero orphaned or partial rows.

### Target Specifications
- **Single Transaction Boundary**: Staging all related entity writes (`task`, `task_assignment_history`, `task_status_history`, `activity_log`, `notification`) inside an active `AsyncSession` before calling `await db.commit()`.
- **Atomic Rollback Guarantee**: If an exception occurs at any point before commit (simulated via `simulate_failure=True` or unexpected database/network faults), `await db.rollback()` is invoked and the database remains in its exact pre-operation state (0 partial rows persisted).
- **Project Membership Validation**: Assignees must be validated against `project_user` membership when memberships exist. Assigning tasks to non-members is rejected immediately with HTTP 400 (`PROJECT_MEMBERSHIP_REQUIRED`), preventing invalid assignments and guaranteeing zero database mutations.
- **Transactional Notification Outbox**: Notifications are created transactionally in `pending` status within the database boundary. Actual dispatch (email/push/webhook) is decoupled from the transaction, eliminating partial state if dispatch fails.

### Verification Execution Summary

#### 1. Success Case State Transition
| Entity / Table | Pre-Operation State | Post-Success State (`assignee_id = 15`) | Net Mutation |
|---|---|---|---|
| `task` | `status = todo`, `assignee_id = None` | `status = in_progress`, `assignee_id = 15` | 1 row updated |
| `task_assignment_history` | 0 rows | 1 row (`prev=None`, `new=15`) | +1 row |
| `task_status_history` | 0 rows | 1 row (`todo -> in_progress`) | +1 row |
| `activity_log` | 0 rows | 1 row (`action='TASK_ASSIGNED'`) | +1 row |
| `notification` | 0 rows | 1 row (`status='pending'`, recipient=15) | +1 row |

#### 2. Mid-Transaction Failure & Rollback Proof
When reassigning from Bob (`15`) to Charlie with `simulate_failure=True`:
- Forced mid-flow exception: `TransactionSimulationError: Simulated failure midway through task assignment transaction`
- Database rollback invoked: `await db.rollback()`
- Re-query results (`db_session.expire_all()`):
  - `task.assignee_id` remains Bob (`15`)
  - `task.status` remains `in_progress`
  - `task_assignment_history` count remains 1 (0 rows for Charlie)
  - `task_status_history` count remains 1
  - `activity_log` count remains 1
  - `notification` count remains 1
  - **Atomicity Checklist**: All checks **PASS** with 0 partial writes.

For full logs, SQL inspection, and Loom video evidence, see [`demos/01-transaction-safe-assignment/demo.md`](../demos/01-transaction-safe-assignment/demo.md).

---

## 3. Migration Safety SLO

### Objective
All Alembic schema migrations must execute cleanly forward (`alembic upgrade head`) and backward (`alembic downgrade -1`) on both empty databases and databases populated with seed data. Migrations that add non-nullable columns must use a 3-phase backfill strategy. DB-level constraints must be named explicitly to support reliable downgrade.

### Target Specifications
- **Forward migration on clean DB**: All 3 migrations apply in sequence without error.
- **`downgrade -1`**: Migration 3 rolls back cleanly, restoring the schema to migration 2 state.
- **Forward migration on seeded DB**: Migration 3 bacfills `project.slug` from existing `project.name` rows without error.
- **Constraint enforcement**: DB rejects invalid rows (`UNIQUE`, `CHECK`) independently of the API layer.

### Migration Inventory

| # | Revision | Description | Type |
|---|----------|-------------|------|
| 1 | `aae8fcd27de6` | Initial schema: `user`, `project`, `project_user`, `task` + enums | Autogenerated |
| 2 | `096305ddb2ff` | History/audit tables: `activity_log`, `notification`, `task_assignment_history`, `task_status_history` | Autogenerated |
| 3 | `cd823c0995ed` | `project.slug` (3-phase backfill), check constraints, named indexes | **Autogenerated + Hand-edited** |

### Execution Results

#### `alembic upgrade head` — Clean Database
```text
$ uv run alembic upgrade head
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> aae8fcd27de6, initial schema
INFO  [alembic.runtime.migration] Running upgrade aae8fcd27de6 -> 096305ddb2ff, add_assignment_and_audit_tables
INFO  [alembic.runtime.migration] Running upgrade 096305ddb2ff -> cd823c0995ed, add_project_slug_and_db_constraints
```

#### `alembic downgrade -1`
```text
$ uv run alembic downgrade -1
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade cd823c0995ed -> 096305ddb2ff, add_project_slug_and_db_constraints
```

#### `alembic upgrade head` — Seeded Database (backfill proof)
```text
$ uv run alembic upgrade head          # after make seed (5 projects, no slugs)
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 096305ddb2ff -> cd823c0995ed, add_project_slug_and_db_constraints

Backfilled project slugs:
  1  TaskFlow Backend MVP              →  taskflow-backend-mvp-1
  2  Database Migration Suite          →  database-migration-suite-2
  3  Authentication & Security Service →  authentication-security-service-3
  4  Real-time Notification Engine     →  real-time-notification-engine-4
  5  API Gateway Redesign              →  api-gateway-redesign-5
```

#### Constraint Violation Evidence
```text
-- Duplicate email → UniqueViolationError: "user_email_key"
INSERT INTO "user" (name, email) VALUES ('Clone', 'morgan.smith1@example.com');
ERROR: duplicate key value violates unique constraint "user_email_key"

-- Duplicate slug → UniqueViolationError: "uq_project_slug"
INSERT INTO project (name, slug) VALUES ('Dup', 'taskflow-backend-mvp-1');
ERROR: duplicate key value violates unique constraint "uq_project_slug"

-- Bad notification status → CheckViolationError: "ck_notification_status"
INSERT INTO notification (recipient_id, type, status) VALUES (1, 'TEST', 'dispatched');
ERROR: new row for relation "notification" violates check constraint "ck_notification_status"

-- Bad entity_type → CheckViolationError: "ck_activity_log_entity_type"
INSERT INTO activity_log (entity_type, entity_id, action) VALUES ('invoice', 99, 'CREATED');
ERROR: new row for relation "activity_log" violates check constraint "ck_activity_log_entity_type"
```

For full logs, backfill details, and Loom video, see [`demos/02-alembic-migrations/demo.md`](../demos/02-alembic-migrations/demo.md).

---

## 4. Query Performance SLO

### Objective
Task filtering queries on large datasets (10,000+ rows) must show measurable performance improvement after adding index strategies, documented via `EXPLAIN ANALYZE`.
