# Demo: Transaction-Safe Task Assignment Flow

## Loom Video
https://www.loom.com/share/08584079a2994335b8feac81cf75b7a8

https://www.loom.com/share/aa15d643939b4fd6a514f8746d272f8b



## Objective
Demonstrate that assigning or reassigning a task across multiple database entities (`task`, `task_assignment_history`, `task_status_history`, `activity_log`, `notification`) operates within a single, atomic transaction boundary. Prove both:
1. **Success Case**: All tables are written consistently and atomically in one transaction.
2. **Failure Case (Forced mid-transaction exception)**: Database state is completely rolled back with zero partial/orphaned rows written.

## Scenario
A team lead assigns a task to an engineer while transitioning its status to `in_progress`.
- The operation must:
  1. Update `task.assignee_id` and `task.status`.
  2. Insert an audit record in `task_assignment_history` tracking old vs. new assignee (only if assignee changed).
  3. Insert a transition record in `task_status_history` (only if status changed).
  4. Insert an activity trail entry in `activity_log`.
  5. Insert a pending notification in `notification` (for asynchronous outbox delivery).
- If an unexpected error or mid-flow exception occurs prior to committing (after all 5 records are staged), the entire transaction rolls back cleanly, leaving all tables in their exact pre-operation state.

## Commands / Steps Used

### 1. Run Migrations
```bash
uv run alembic upgrade head
```

### 2. Run Interactive Demo Script
```bash
uv run python scripts/demo_transaction_safe_assignment.py
```

### 3. Run Automated Tests
```bash
uv run pytest tests/services/test_task_assignment_transaction.py -v
uv run pytest tests/api/test_tasks_assignment_api.py -v
```

## Expected Behavior
1. **Initial State**: Unassigned task exists, 0 rows in history/log/notification tables.
2. **Successful Assignment**: Task is updated (`assignee_id = 5`, `status = in_progress`), and exactly 1 row is added to each of `task_assignment_history`, `task_status_history`, `activity_log`, and `notification`.
3. **Mid-Transaction Failure**: Forced exception (`TransactionSimulationError`) is caught. Database rollback ensures:
   - `task` remains assigned to Bob (`assignee_id = 5`).
   - Counts of `task_assignment_history`, `task_status_history`, `activity_log`, and `notification` remain at 1 (no partial rows for Charlie).
   - All checklist items report `PASS`.

## Actual Findings

### 1. Interactive Demo Output
```text
 STEP 1: Seeding Initial Data (Project, 2 Users, 1 Task)

======================================================================
DB SNAPSHOT: INITIAL STATE (Unassigned Task)
======================================================================
Task ID=2 | Title='Implement Transaction Safety' | Status='todo' | Assignee ID=None

[Table: task_assignment_history] -> Total Rows: 0

[Table: task_status_history] -> Total Rows: 0

[Table: activity_log] -> Total Rows: 0

[Table: notification] -> Total Rows: 0
======================================================================


⚡ STEP 2: Executing Successful Task Assignment (Assigning to Bob)...

======================================================================
 DB SNAPSHOT: AFTER SUCCESSFUL TRANSACTION (Bob Assigned)
======================================================================
Task ID=2 | Title='Implement Transaction Safety' | Status='in_progress' | Assignee ID=5

[Table: task_assignment_history] -> Total Rows: 1
  - ID=2 | prev=None | new=5 | by=4 | created_at=2026-09-09 16:27:41.351952+00:00

[Table: task_status_history] -> Total Rows: 1
  - ID=2 | prev_status=todo | new_status=in_progress | changed_by=4 | created_at=2026-09-09 16:27:41.351952+00:00

[Table: activity_log] -> Total Rows: 1
  - ID=2 | actor_id=4 | action='TASK_ASSIGNED' | details={'new_status': 'in_progress', 'status_changed': True, 'new_assignee_id': 5, 'previous_status': 'todo', 'assignee_changed': True, 'previous_assignee_id': None} | created_at=2026-09-09 16:27:41.351952+00:00

[Table: notification] -> Total Rows: 1
  - ID=2 | recipient=5 | type='TASK_ASSIGNED' | status='pending' | payload={'task_id': 2, 'task_title': 'Implement Transaction Safety', 'assigned_by_id': 4} | created_at=2026-09-09 16:27:41.351952+00:00
======================================================================


⚡ STEP 3: Attempting Reassignment to Charlie with SIMULATED FAILURE...
 Expected Exception Caught: Simulated failure midway through task assignment transaction

======================================================================
 DB SNAPSHOT: AFTER FORCED FAILURE (Rollback Proof: State Unchanged)
======================================================================
Task ID=2 | Title='Implement Transaction Safety' | Status='in_progress' | Assignee ID=5

[Table: task_assignment_history] -> Total Rows: 1
  - ID=2 | prev=None | new=5 | by=4 | created_at=2026-09-09 16:27:41.351952+00:00

[Table: task_status_history] -> Total Rows: 1
  - ID=2 | prev_status=todo | new_status=in_progress | changed_by=4 | created_at=2026-09-09 16:27:41.351952+00:00

[Table: activity_log] -> Total Rows: 1
  - ID=2 | actor_id=4 | action='TASK_ASSIGNED' | details={'new_status': 'in_progress', 'status_changed': True, 'new_assignee_id': 5, 'previous_status': 'todo', 'assignee_changed': True, 'previous_assignee_id': None} | created_at=2026-09-09 16:27:41.351952+00:00

[Table: notification] -> Total Rows: 1
  - ID=2 | recipient=5 | type='TASK_ASSIGNED' | status='pending' | payload={'task_id': 2, 'task_title': 'Implement Transaction Safety', 'assigned_by_id': 4} | created_at=2026-09-09 16:27:41.351952+00:00
======================================================================


======================================================================
🔍 TRANSACTION ROLLBACK VERIFICATION CHECKLIST
======================================================================
[✅ PASS] Task Assignee Unchanged (Still Bob)
[✅ PASS] Task Status Unchanged (Still in_progress)
[✅ PASS] No Partial Assignment History Persisted
[✅ PASS] No Partial Status History Persisted
[✅ PASS] No Partial Activity Log Persisted
[✅ PASS] No Partial Notification Persisted
======================================================================
 ALL ATOMICITY CHECKS PASSED: Rollback fully verified!
======================================================================
```

### 2. Pytest Execution Evidence
```text
============================= test session starts ==============================
collected 11 items

tests/services/test_task_assignment_transaction.py::test_assign_task_success_all_records_created PASSED [  9%]
tests/services/test_task_assignment_transaction.py::test_reassign_task_success PASSED [ 18%]
tests/services/test_task_assignment_transaction.py::test_assign_task_without_status_transition PASSED [ 27%]
tests/services/test_task_assignment_transaction.py::test_unassign_task_success PASSED [ 36%]
tests/services/test_task_assignment_transaction.py::test_assign_task_mid_transaction_failure_rolls_back_everything PASSED [ 45%]
tests/services/test_task_assignment_transaction.py::test_assign_task_nonexistent_user_raises_not_found PASSED [ 54%]
tests/services/test_task_assignment_transaction.py::test_assign_task_non_member_raises_membership_error PASSED [ 63%]
tests/services/test_task_assignment_transaction.py::test_assign_task_non_member_does_not_mutate_db PASSED [ 72%]
tests/api/test_tasks_assignment_api.py::test_api_assign_task_success PASSED [ 81%]
tests/api/test_tasks_assignment_api.py::test_api_assign_task_failure_rollback PASSED [ 90%]
tests/api/test_tasks_assignment_api.py::test_api_assign_task_non_member_returns_400 PASSED [100%]

============================== 11 passed in 1.18s ==============================
```

## Evidence
- **Before / After Success Snapshots**: Step 1 & Step 2 show complete state transitions across all 5 tables.
- **Rollback Proof Snapshot**: Step 3 shows forced failure after staging all records, resulting in 0 partial writes.
- **Automated Tests**: Unit and integration test suite passing with full isolation under `tests/services/test_task_assignment_transaction.py` and `tests/api/test_tasks_assignment_api.py`.

## What We Learned
- Staging all related records (`task`, `task_assignment_history`, `task_status_history`, `activity_log`, `notification`) before `db.commit()` guarantees that partial writes never corrupt database integrity.
- Notification dispatch should be decoupled from creation: inserting a pending record into the `notification` outbox table within the business transaction ensures emails/pushes are only triggered for committed transactions.
- Re-querying the database after `db.rollback()` (and clearing session cache via `expire_all()`) verifies that transactional rollback is enforced at the database engine level.

## Open Questions
- None.
