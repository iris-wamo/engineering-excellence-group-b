# Demo 02 — Domain Workflow Engine

## Loom Video
Paste Loom link here.

## Objective
Prove that task status changes follow one workflow, enforced in one place:

```
todo → in_progress → review → done
```

Adjacent backward moves are allowed so work can be reopened (`in_progress → todo`, `review → in_progress`, `done → review`). Skipping steps (for example `todo → done`) is rejected with a consistent error. Every valid move writes a status history row and an activity log row; a rejected move writes nothing.

## Scenario
A user tries to close a brand-new task by jumping from `todo` straight to `done`. The API refuses. They then move it through the proper steps, send it back for rework once, and finish it. Afterwards the DB shows the full trail.

## Commands / Steps Used
Start the stack and apply migrations (adds the `review` status):

```bash
make docker-up
make migrate
```

Then, with the API on `http://localhost:8000`:

```bash
H='Content-Type: application/json'; API=http://localhost:8000/api/v1

# 1. Create a project and a task (ids are captured into variables)
PID=$(curl -s -X POST $API/projects -H "$H" -d '{"name": "Workflow Demo"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
TID=$(curl -s -X POST $API/tasks -H "$H" -d "{\"title\": \"Implement workflow\", \"project_id\": $PID}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

# 2. Invalid jump: todo -> done
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -d '{"status": "done"}'

# 3. Valid path, with one rework loop
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -d '{"status": "in_progress"}'
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -d '{"status": "review"}'
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -d '{"status": "in_progress"}'
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -d '{"status": "review"}'
curl -s -X PATCH $API/tasks/$TID/status -H "$H" -d '{"status": "done"}'

# 4. Same rule through the assign endpoint (use a fresh todo task, must be rejected)
TID2=$(curl -s -X POST $API/tasks -H "$H" -d "{\"title\": \"Assign check\", \"project_id\": $PID}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
curl -s -X POST $API/tasks/$TID2/assign -H "$H" -d '{"assignee_id": null, "status": "done"}'

# 5. DB check: run `make docker-db-shell`, then
#    SELECT previous_status, new_status FROM task_status_history WHERE task_id = 1 ORDER BY id;
#    SELECT action, details FROM activity_log WHERE entity_type = 'task' AND entity_id = 1 ORDER BY id;
#    (replace 1 with the value of $TID)
```

Tests: `uv run pytest tests/api/test_task_workflow.py tests/api/test_tasks_assignment_api.py -v`

## Expected Behavior
- `todo -> done` returns `400` with code `INVALID_STATUS_TRANSITION` and nothing is written.
- Each valid move returns `200` with the new status.
- The assign endpoint applies the same rule: `{"status": "done"}` on a `todo` task returns `400` and the task is left unchanged.
- `task_status_history` and `activity_log` get one row per valid move.

## Actual Findings
Run against the local API and Postgres on 2026-10-06:

- `todo -> done` returned `400` with a clean error body.
- `todo -> in_progress -> review -> in_progress -> review -> done` all returned `200`.
- The assign endpoint with `status: done` on a `todo` task returned `400` with the same error.
- 5 history rows and 5 activity log rows were written, one per valid move. The rejected move wrote none.
- `changed_by_id` / `actor_id` are `NULL` for the status endpoint, because the endpoint does not yet know who the caller is.

## Evidence
Invalid move — `PATCH /api/v1/tasks/201/status {"status": "done"}` → `400`:
```json
{
  "error": {
    "code": "INVALID_STATUS_TRANSITION",
    "message": "Cannot transition task from todo to done",
    "details": [{"field": "status", "message": "Invalid transition from todo to done"}]
  }
}
```

Same rule via assign — `POST /api/v1/tasks/{id}/assign {"assignee_id": null, "status": "done"}` → `400`:
```json
{
  "error": {
    "code": "INVALID_STATUS_TRANSITION",
    "message": "Cannot transition task from todo to done",
    "details": [{"field": "status", "message": "Invalid transition from todo to done"}]
  }
}
```

Status history after the valid path:
```
 previous_status | new_status
-----------------+-------------
 todo            | in_progress
 in_progress     | review
 review          | in_progress
 in_progress     | review
 review          | done
```

Activity log after the valid path:
```
     action     |                          details
----------------+------------------------------------------------------------
 STATUS_CHANGED | {"new_status": "in_progress", "previous_status": "todo"}
 STATUS_CHANGED | {"new_status": "review", "previous_status": "in_progress"}
 STATUS_CHANGED | {"new_status": "in_progress", "previous_status": "review"}
 STATUS_CHANGED | {"new_status": "review", "previous_status": "in_progress"}
 STATUS_CHANGED | {"new_status": "done", "previous_status": "review"}
```

## What We Learned
Put the state machine in one workflow class and make every entry point call it. The status endpoint and the assign endpoint both change status, and the rules only hold because both go through `TaskWorkflow`. Validating before writing also means a rejected move leaves no partial history.

## Open Questions
- Who made the change? `changed_by_id` and `actor_id` stay empty until the API knows the current user (planned with RBAC).
- Should setting a task to the status it already has be a quiet no-op instead of a `400`?
- Should reopening a finished task (`done → review`) be allowed for everyone, or only for certain roles?
