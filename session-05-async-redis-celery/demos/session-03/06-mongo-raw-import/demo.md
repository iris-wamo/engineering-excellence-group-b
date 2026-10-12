# Demo 06 — MongoDB Raw Task Import & PostgreSQL Linkage

## Loom Video
[Watch Demo Recording](https://www.loom.com/share/86b51f9634e747bcbd2fe0949cfc9f83)

## Objective
Demonstrate the **Import Debuggability SLO**: raw/semi-structured task import payloads belong in a document store (MongoDB) before validation/normalization into a relational schema (PostgreSQL), ensuring failed imports remain traceable with error details rather than being silently dropped or corrupting the relational database.

## Architecture & Workflow
When importing tasks from external webhooks (e.g., Jira, Trello), payloads often carry varying, semi-structured metadata that does not fit into a strict PostgreSQL relational schema.

1. **Ingest Raw Payload (MongoDB):** The raw JSON payload is saved to MongoDB (`raw_task_imports`) with `status: "PENDING"`.
2. **Normalize & Validate (PostgreSQL):** The required fields are extracted and validated against our domain models (`TaskStatus`, `TaskPriority`, `Project`).
3. **Bidirectional Linkage:**
   - **On Success:** A PostgreSQL `task` row is created storing `mongo_import_id`. The MongoDB document is updated to `status: "SUCCESS"` and records `postgres_task_id`. Extra metadata (e.g., `jira_key`) remains safely stored in MongoDB.
   - **On Failure:** PostgreSQL transaction is rolled back (0 corrupt rows inserted). The MongoDB document is updated to `status: "FAILED"` and records the exception in `error_details` for debugging.

---

## Commands & Execution Outputs

### 1. Apply Migration
Run Alembic forward to add the `mongo_import_id` column to PostgreSQL:
```bash
uv run alembic upgrade head
```
```text
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade aae8fcd27de6 -> 5c60a4a4906c, add_mongo_import_id_to_task
```

### 2. Seed Baseline Data
Seed projects and users required for foreign key relationships:
```bash
make seed
```
```text
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
Time Taken       : 0.15 seconds
--------------------------------------------------
Table Name           | Row Count
--------------------------------------------------
user                 | 10
project              | 5
project_user         | 23
task                 | 200
==================================================
```

### 3. Run Ingestion Script
Execute the import pipeline demonstrating both a successful payload and a failing payload:
```bash
uv run python scripts/demo_mongo_import.py
```
```text
============================================================
 DEMO 06 — Mongo Raw Import → Postgres Normalisation
============================================================

✅  Successful import  — Postgres task.id=201
{
  "_id": "6abd04d5c4772ea68f8fecb8",
  "raw_payload": {
    "summary": "Implement OAuth2 SSO",
    "project_id": 1,
    "status": "in_progress",
    "priority": "high",
    "jira_key": "SEC-402"
  },
  "status": "SUCCESS",
  "postgres_task_id": 201,
  "error_details": null,
  "created_at": "2026-09-30T12:47:17.002000",
  "updated_at": "2026-09-30T12:47:17.053000"
}

❌  Failed import (bad priority)  — 'ULTRA_HIGH' is not a valid TaskPriority
{
  "_id": "6abd04d5c4772ea68f8fecb9",
  "raw_payload": {
    "title": "Broken task",
    "project_id": 1,
    "priority": "ULTRA_HIGH"
  },
  "status": "FAILED",
  "postgres_task_id": null,
  "error_details": {
    "message": "'ULTRA_HIGH' is not a valid TaskPriority",
    "type": "ValueError"
  },
  "created_at": "2026-09-30T12:47:17.056000",
  "updated_at": "2026-09-30T12:47:17.057000"
}

============================================================
 DEMO COMPLETE
============================================================
```

### 4. Revert Migration (Clean Rollback)
Verify revertability per schema migration standards:
```bash
uv run alembic downgrade -1
```
```text
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 5c60a4a4906c -> aae8fcd27de6, add_mongo_import_id_to_task
```

---

## Evidence & Verification

### PostgreSQL Verification (DBeaver)
1. **Successful Linkage:**
   ```sql
   SELECT id, title, status, priority, project_id, mongo_import_id
   FROM task
   WHERE mongo_import_id IS NOT NULL;
   ```
   *Result:* Task row 201 contains `mongo_import_id = '6abd04d5c4772ea68f8fecb8'`, linking directly back to MongoDB.

2. **Schema Protection on Failure:**
   ```sql
   SELECT * FROM task WHERE title = 'Broken task';
   ```
   *Result:* Returns `0 rows`. The invalid payload was rejected and never inserted into PostgreSQL.

### MongoDB Verification (Compass / CLI)
- **Extra Metadata Preserved:** The successful document retains `"jira_key": "SEC-402"` inside `raw_payload`.
- **Error Traceability:** The failed document contains `status: "FAILED"`, `postgres_task_id: null`, and the exact exception:
  ```json
  "error_details": {
    "message": "'ULTRA_HIGH' is not a valid TaskPriority",
    "type": "ValueError"
  }
  ```

---

## What We Learned
1. **Document Store for Ingestion Buffer:** MongoDB allows ingesting arbitrary webhook payloads without premature schema migrations or losing unmapped attributes.
2. **Import Debuggability SLO:** Failed webhook imports do not vanish into application logs; they remain queryable in MongoDB with full payloads and stack traces.
3. **Relational Integrity:** PostgreSQL enforces strict schema validation and foreign keys, rolling back cleanly whenever invalid records arrive.
4. **Bidirectional Traceability:** Engineers can seamlessly cross-reference records starting from either PostgreSQL (`Task.mongo_import_id`) or MongoDB (`postgres_task_id`).
