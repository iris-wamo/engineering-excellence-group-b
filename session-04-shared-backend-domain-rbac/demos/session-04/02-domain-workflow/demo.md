# Demo 02 — Domain Workflow Engine

## Loom Video
https://www.loom.com/share/example-domain-workflow-engine

## Objective
We are proving that tasks follow the transition path `todo` → `in_progress` → `review` → `done`, while allowing adjacent reversals such as `in_progress` → `todo` when a task needs to be reopened or corrected. Invalid jumps still fail, and valid moves create history and activity records.

## Scenario
A user attempts to move a task from `todo` to `done` directly (bypassing progress and review), which fails. They then move it correctly to `in_progress`, and later they may move it back to `todo` if the task needs to be reopened without skipping the required review gate on future forward progress.

## Commands / Steps Used
- Create a task: `curl -X POST /api/v1/tasks -d '{"title": "Implement workflow", "project_id": 1}'`
- Attempt invalid transition (todo -> done): `curl -X PATCH /api/v1/tasks/1/status -d '{"status": "done"}'`
- Perform valid transition (todo -> in_progress): `curl -X PATCH /api/v1/tasks/1/status -d '{"status": "in_progress"}'`

## Expected Behavior
- The invalid transition should return a 400 Bad Request with `INVALID_STATUS_TRANSITION` error.
- The valid transition should succeed and return the task with the new status, recording history.

## Actual Findings
- The invalid transition correctly returned 400 with a clean error message.
- The valid transition returned 200 and updated the status to `in_progress`. History records were written in the DB.

## Evidence
Invalid Move Request/Response:
```json
// PATCH /api/v1/tasks/1/status {"status": "done"}
{
  "error": {
    "code": "INVALID_STATUS_TRANSITION",
    "message": "Cannot transition task from todo to done",
    "details": [{"field": "status", "message": "Invalid transition from todo to done"}]
  }
}
```

Valid Move History Records (DB Output):
```sql
SELECT previous_status, new_status FROM task_status_history WHERE task_id = 1;
-- previous_status | new_status
-- todo            | in_progress

SELECT action FROM activity_log WHERE entity_id = 1 AND entity_type = 'task';
-- STATUS_CHANGED
```

## What We Learned
Enforcing state machine rules centrally in a workflow class ensures all pathways (API, internal services, background jobs) conform to the exact same business logic.

## Open Questions
None currently.
