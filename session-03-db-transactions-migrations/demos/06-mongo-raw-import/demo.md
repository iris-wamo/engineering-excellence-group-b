# Demo 06 — MongoDB Raw Task Import & PostgreSQL Linkage

## Loom Video
<!-- Replace with actual Loom link after recording -->

## Objective
Show when raw/semi-structured import data belongs in a document store (MongoDB) vs. a relational schema (PostgreSQL), and how failed imports stay traceable instead of being silently dropped.

## How to Run
```bash
docker compose up -d db mongo        # Postgres on :5433, Mongo on :27017
uv run alembic upgrade head
make seed                            # need at least one project
uv run python scripts/demo_mongo_import.py
```

## What the Script Does
1. Receives a raw JSON payload (like a Jira/Trello webhook).
2. Stores the **full raw payload** in MongoDB (`raw_task_imports`) with `status: "PENDING"`.
3. Validates and normalizes it into a PostgreSQL `task` row.
4. Updates the Mongo document:
   - **Success** → `status: "SUCCESS"`, stores `postgres_task_id`.
   - **Failure** → `status: "FAILED"`, stores `error_details` (no Postgres row created).

## Evidence — `find()` Output

### Successful Import
```json
{
  "_id": "6ab43c6473ac520ff34f3374",
  "raw_payload": {
    "summary": "Implement OAuth2 SSO",
    "project_id": 1,
    "status": "in_progress",
    "priority": "high",
    "jira_key": "SEC-402"
  },
  "status": "SUCCESS",
  "postgres_task_id": 201,
  "error_details": null
}
```
The `jira_key` field (not part of the Postgres schema) is preserved in Mongo.
Postgres `task` row has `mongo_import_id = "6ab43c6473ac520ff34f3374"` for back-reference.

### Failed Import
```json
{
  "_id": "6ab43c6473ac520ff34f3375",
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
  }
}
```
No orphan row in Postgres. The raw payload + error details stay queryable in Mongo for debugging.

## What We Learned
1. **Document store for raw ingestion** — MongoDB naturally handles varying/unknown fields (`jira_key`, `external_metadata`, etc.) that don't fit a fixed relational schema.
2. **Failed imports stay traceable** — Instead of silently dropping bad data, `status: "FAILED"` + `error_details` in Mongo fulfils the Import Debuggability SLO.
3. **Bidirectional linkage** — `Task.mongo_import_id` (Postgres → Mongo) and `postgres_task_id` (Mongo → Postgres) let you trace data in either direction.
4. **Clean revertability** — `alembic downgrade -1` removes the `mongo_import_id` column; `docker compose down mongo` removes the Mongo container.

## How to Revert
```bash
uv run alembic downgrade -1          # drops mongo_import_id column
docker compose down mongo             # stops & removes mongo container
```
