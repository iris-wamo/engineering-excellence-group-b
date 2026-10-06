# Raw Import Normalization

## 1. Overview & Problem Statement
When ingesting task data from external webhooks, third-party issue trackers (e.g. Jira, Trello, Linear), or batch CSV/JSON exports, incoming payloads are semi-structured, noisy, and frequently carry non-relational metadata or invalid foreign keys.

Directly inserting raw data into PostgreSQL leads to:
1. **Silent Failures**: Rejections on database constraints drop external payloads without traceable audit trails.
2. **Context Loss**: Useful third-party attributes (`jira_key`, custom sprint labels, external author IDs) are discarded because they do not fit relational schema columns.
3. **Debugging Impasse**: Engineers cannot inspect the original payload that caused an error.

To resolve this, TaskFlow implements the **Store Raw First, Then Normalize** architectural pattern.

---

## 2. Ingestion & Normalization Architecture

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 INCOMING RAW PAYLOAD                                   │
│   { "summary": "Fix SSO", "project_id": 1, "priority": "high", "jira_key": "SEC-402" } │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        STEP 1: STAGE RAW IN MONGODB (PENDING)                          │
│ Collection: raw_task_imports                                                           │
│ {                                                                                      │
│   "_id": ObjectId("6701..."),                                                          │
│   "raw_payload": { ... },                                                              │
│   "status": "PENDING",                                                                 │
│   "postgres_task_id": null,                                                            │
│   "error_details": null,                                                               │
│   "created_at": ISODate(...),                                                          │
│   "updated_at": ISODate(...)                                                           │
│ }                                                                                      │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        STEP 2: VALIDATE & NORMALIZE (POSTGRESQL)                       │
│                                                                                        │
│   ┌────────────────────────────────────────┐ ┌──────────────────────────────────────┐  │
│   │               SUCCESS                  │ │                FAILURE               │  │
│   │  • Title extracted & stripped          │ │  • Project ID does not exist         │  │
│   │  • Enums mapped (TaskStatus/Priority)  │ │  • Invalid priority enum             │  │
│   │  • Project & Assignee verified         │ │  • Missing title/summary             │  │
│   │  • INSERT INTO task (...)              │ │  • DB Rollback (0 rows added)        │  │
│   │  • Commit transaction                  │ │                                      │  │
│   └───────────────────┬────────────────────┘ └───────────────────┬──────────────────┘  │
└───────────────────────┼──────────────────────────────────────────┼─────────────────────┘
                        │                                          │
                        ▼                                          ▼
┌────────────────────────────────────────────┐ ┌─────────────────────────────────────────┐
│        STEP 3A: UPDATE MONGO (SUCCESS)     │ │        STEP 3B: UPDATE MONGO (FAILED)   │
│ {                                          │ │ {                                       │
│   "status": "SUCCESS",                     │ │   "status": "FAILED",                   │
│   "postgres_task_id": 142,                 │ │   "error_details": {                    │
│   "updated_at": ISODate(...)               │ │     "type": "ValueError",               │
│ }                                          │ │     "message": "Project 999 not found"  │
│                                            │ │   },                                    │
│ PostgreSQL task row:                       │ │   "updated_at": ISODate(...)            │
│ id=142, mongo_import_id="6701..."          │ │ }                                       │
└────────────────────────────────────────────┘ └─────────────────────────────────────────┘
```

---

## 3. Data Boundary: What Stays Raw vs What Becomes Structured

| Field / Attribute | Stored in MongoDB (`raw_task_imports`) | Stored in PostgreSQL (`task`) | Rationale |
|---|:---:|:---:|---|
| **Raw JSON Payload** |  **YES** | ❌ No | Schema flexibility, full reproduction capability, audit log. |
| **Ingestion Timestamp** |  **YES** | ❌ No | Tracks when the external payload was received. |
| **Import Status & Error Details** |  **YES** | ❌ No | Failed import attempts must not pollute relational tables. |
| **External Metadata (`jira_key`, tags)** |  **YES** | ❌ No | Preserves third-party context without bloating relational schema. |
| **`title` / `summary`** | Preserved in payload |  **YES** (`title`) | Extracted (`title` or fallback `summary`), trimmed, and validated. |
| **`description`** | Preserved in payload |  **YES** (`description`) | Optional task body text. |
| **`status`** | Preserved in payload |  **YES** (`enum task_status`) | Mapped to strict state machine (`todo`, `in_progress`, `done`). |
| **`priority`** | Preserved in payload |  **YES** (`enum task_priority`)| Mapped to strict priority index (`low`, `medium`, `high`, `urgent`).|
| **`project_id`** | Preserved in payload |  **YES** (`FK -> project.id`) | Foreign key enforcement with relational integrity. |
| **`assignee_id`** | Preserved in payload |  **YES** (`FK -> user.id`) | Foreign key with project membership verification. |
| **`mongo_import_id`** | Generated `_id` |  **YES** (`task.mongo_import_id`)| Bidirectional linkage from relational row back to raw document. |

---

## 4. Normalization & Fallback Rules
1. **Title / Summary**:
   - Primary: `raw_payload["title"]`
   - Fallback: `raw_payload["summary"]`
   - Validation: Must be non-empty after whitespace trimming.
2. **Status**:
   - Case-insensitive string matching to `TaskStatus` (`todo`, `in_progress`, `done`).
   - Defaults to `TaskStatus.todo` if omitted.
3. **Priority**:
   - Case-insensitive string matching to `TaskPriority` (`low`, `medium`, `high`, `urgent`).
   - Defaults to `TaskPriority.medium` if omitted.
4. **Project Relationship**:
   - `project_id` must be an integer pointing to an existing `project` row.
5. **Assignee & Membership**:
   - Optional `assignee_id`. If provided, assignee user must exist and be an active member of the target project.

---

## 5. API Endpoints

### Ingest Raw Task
- **Endpoint**: `POST /api/v1/tasks/import`
- **Request Body**:
  ```json
  {
    "raw_payload": {
      "summary": "Implement OAuth2 SSO",
      "project_id": 1,
      "priority": "high",
      "jira_key": "SEC-402"
    }
  }
  ```
- **Success Response (`201 Created`)**:
  ```json
  {
    "import_id": "6701a2b3c4d5e6f7a8b9c0d1",
    "status": "SUCCESS",
    "postgres_task_id": 142,
    "error_details": null,
    "created_at": "2026-10-06T11:00:00Z",
    "updated_at": "2026-10-06T11:00:01Z"
  }
  ```
- **Failure Response (`200 OK`)**:
  ```json
  {
    "import_id": "6701a2b3c4d5e6f7a8b9c0d2",
    "status": "FAILED",
    "postgres_task_id": null,
    "error_details": {
      "type": "ValueError",
      "message": "Project 999 not found."
    },
    "created_at": "2026-10-06T11:00:00Z",
    "updated_at": "2026-10-06T11:00:01Z"
  }
  ```

### Inspect Raw Import
- **Endpoint**: `GET /api/v1/tasks/import/{import_id}`
- Returns full audit details including original `raw_payload`.

### Batch Ingest Raw Tasks
- **Endpoint**: `POST /api/v1/tasks/import/batch`
- **Request Body**:
  ```json
  {
    "items": [
      {
        "raw_payload": {
          "summary": "Task 1",
          "project_id": 1,
          "priority": "high"
        }
      },
      {
        "raw_payload": {
          "summary": "Task 2",
          "project_id": 1,
          "priority": "medium"
        }
      }
    ]
  }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "total": 2,
    "succeeded": 2,
    "failed": 0,
    "results": [
      {
        "import_id": "6701a2b3c4d5e6f7a8b9c0d1",
        "status": "SUCCESS",
        "postgres_task_id": 142,
        "error_details": null,
        "created_at": "2026-10-06T11:00:00Z",
        "updated_at": "2026-10-06T11:00:01Z"
      },
      {
        "import_id": "6701a2b3c4d5e6f7a8b9c0d2",
        "status": "SUCCESS",
        "postgres_task_id": 143,
        "error_details": null,
        "created_at": "2026-10-06T11:00:00Z",
        "updated_at": "2026-10-06T11:00:01Z"
      }
    ]
  }
  ```

