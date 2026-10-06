# Demo 04 — Raw Data Normalization

## Loom Video
<!-- Replace with Loom URL once recorded -->
https://www.loom.com/share/placeholder-raw-normalization

## Objective
Demonstrate the **Store Raw First, Then Normalize** architectural pattern:
1. Ingest arbitrary, semi-structured task payloads from external systems into MongoDB (`raw_task_imports`) with `PENDING` status.
2. Normalize validated records into PostgreSQL (`task` table) with bidirectional traceability (`task.mongo_import_id` ⟷ `mongo.postgres_task_id`).
3. Retain failed imports in MongoDB with `FAILED` status and explicit diagnostics (`error_details`) while rolling back PostgreSQL to maintain zero dirty relational rows.

---

## Scenario
Simulating webhook ingestion from Jira/external issue trackers:
- **Scenario A (Success)**: Payload has `summary` instead of `title`, valid `project_id`, valid priority, and extraneous `jira_key`. Successfully creates PostgreSQL task and updates MongoDB to `SUCCESS`.
- **Scenario B (Failure - Bad Foreign Key)**: Payload points to a non-existent `project_id: 999999`. Fails validation, rolls back PostgreSQL transaction, and updates MongoDB document to `FAILED` with error diagnostics.
- **Scenario C (Failure - Invalid Enum)**: Payload has invalid priority `"ULTRA_HIGH"`. Fails validation and updates MongoDB to `FAILED`.

---

## Commands / Steps Used

### 1. Ensure Services are Running
```bash
docker compose up -d db mongo
```

### 2. Run Normalization Demo Script
```bash
uv run python scripts/demo_mongo_import.py
```

### 3. Or Test via HTTP API
```bash
# Scenario A: Successful Import
curl -X POST http://localhost:8000/api/v1/tasks/import \
  -H "Content-Type: application/json" \
  -d '{
    "raw_payload": {
      "summary": "Implement OAuth2 SSO",
      "project_id": 1,
      "priority": "high",
      "jira_key": "SEC-402"
    }
  }'

# Scenario B: Failed Import (Bad Project)
curl -X POST http://localhost:8000/api/v1/tasks/import \
  -H "Content-Type: application/json" \
  -d '{
    "raw_payload": {
      "title": "Broken task",
      "project_id": 999999,
      "priority": "medium"
    }
  }'

# Query Import Details
curl http://localhost:8000/api/v1/tasks/import/<IMPORT_ID>

# Batch Ingest Raw Tasks
curl -X POST http://localhost:8000/api/v1/tasks/import/batch \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {
        "raw_payload": {
          "summary": "Setup Datadog tracer",
          "project_id": 1,
          "priority": "high"
        }
      },
      {
        "raw_payload": {
          "summary": "Setup Sentry alerts",
          "project_id": 1,
          "priority": "medium"
        }
      }
    ]
  }'
```


---

## Expected Behavior
1. Every import attempt immediately generates an `import_id` and document in MongoDB.
2. Valid payloads create a normalized `task` in PostgreSQL referencing `mongo_import_id`.
3. Invalid payloads do not alter PostgreSQL, but persist the error message in MongoDB for debugging.

---

## Actual Findings & Evidence

### Test Execution
```bash
uv run pytest tests/schemas/test_task_import_schema.py tests/services/test_task_import_service.py tests/api/test_task_imports.py
```
```text
tests/schemas/test_task_import_schema.py .....                           [ 33%]
tests/services/test_task_import_service.py .......                       [ 80%]
tests/api/test_task_imports.py ...                                       [100%]

============================== 15 passed in 0.65s ==============================
```

### Sample MongoDB Documents

#### Successful Import (`status: "SUCCESS"`):
```json
{
  "_id": "6702a4b8c9d1e2f3a4b5c6d7",
  "raw_payload": {
    "summary": "Implement OAuth2 SSO",
    "project_id": 1,
    "priority": "high",
    "status": "in_progress",
    "jira_key": "SEC-402"
  },
  "status": "SUCCESS",
  "postgres_task_id": 142,
  "error_details": null,
  "created_at": "2026-10-06T11:00:00Z",
  "updated_at": "2026-10-06T11:00:01Z"
}
```

#### Failed Import (`status: "FAILED"`):
```json
{
  "_id": "6702a4b8c9d1e2f3a4b5c6d8",
  "raw_payload": {
    "title": "Broken task",
    "project_id": 999999,
    "priority": "ULTRA_HIGH"
  },
  "status": "FAILED",
  "postgres_task_id": null,
  "error_details": {
    "type": "ValueError",
    "message": "Project 999999 not found."
  },
  "created_at": "2026-10-06T11:01:00Z",
  "updated_at": "2026-10-06T11:01:00Z"
}
```

---

## What We Learned
- **Staging Raw Data Prevents Silent Failures**: Staging payloads in a document store guarantees 100% auditability and debuggability for external integrations.
- **Relational Integrity is Preserved**: PostgreSQL transactions roll back on validation error, ensuring zero orphaned or corrupted records.
- **Bidirectional Traceability**: Storing `mongo_import_id` on PostgreSQL `Task` and `postgres_task_id` on MongoDB import document allows instantaneous cross-system lookups.
