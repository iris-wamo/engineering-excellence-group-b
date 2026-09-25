"""Interactive script demonstrating transaction safety during task assignment.

Demonstrates:
1. DB state before operations.
2. Success case: atomic write to task, task_assignment_history,
   task_status_history, activity_log, notification.
3. Failure case: mid-transaction failure rolls back all partial writes,
   leaving DB state unchanged.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.exceptions import TransactionSimulationError
from app.models.activity_log import ActivityLog
from app.models.enums import ProjectRole, TaskStatus
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory
from app.models.user import User
from app.schemas.task import TaskAssignRequest
from app.services.task_service import TaskService


async def print_db_snapshot(session: AsyncSession, task_id: int, label: str) -> dict:
    print(f"\n{'=' * 70}")
    print(f" DB SNAPSHOT: {label}")
    print(f"{'=' * 70}")

    task = await session.get(Task, task_id)
    if task:
        print(
            f"Task ID={task.id} | Title='{task.title}' | "
            f"Status='{task.status.value}' | Assignee ID={task.assignee_id}"
        )
    else:
        print(f"Task ID={task_id} not found")

    history_records = (
        await session.scalars(
            select(TaskAssignmentHistory)
            .where(TaskAssignmentHistory.task_id == task_id)
            .order_by(TaskAssignmentHistory.id.asc())
        )
    ).all()
    print(f"\n[Table: task_assignment_history] -> Total Rows: {len(history_records)}")
    for h in history_records:
        print(
            f"  - ID={h.id} | prev={h.previous_assignee_id} | "
            f"new={h.new_assignee_id} | by={h.assigned_by_id} | "
            f"created_at={h.created_at}"
        )

    status_records = (
        await session.scalars(
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id == task_id)
            .order_by(TaskStatusHistory.id.asc())
        )
    ).all()
    print(f"\n[Table: task_status_history] -> Total Rows: {len(status_records)}")
    for s in status_records:
        print(
            f"  - ID={s.id} | prev_status={s.previous_status.value} | "
            f"new_status={s.new_status.value} | changed_by={s.changed_by_id} | "
            f"created_at={s.created_at}"
        )

    activity_records = (
        await session.scalars(
            select(ActivityLog)
            .where(
                ActivityLog.entity_type == "task",
                ActivityLog.entity_id == task_id,
            )
            .order_by(ActivityLog.id.asc())
        )
    ).all()
    print(f"\n[Table: activity_log] -> Total Rows: {len(activity_records)}")
    for a in activity_records:
        print(
            f"  - ID={a.id} | actor_id={a.actor_id} | action='{a.action}' | "
            f"details={a.details} | created_at={a.created_at}"
        )

    notifications = (
        await session.scalars(
            select(Notification)
            .where(Notification.task_id == task_id)
            .order_by(Notification.id.asc())
        )
    ).all()
    print(f"\n[Table: notification] -> Total Rows: {len(notifications)}")
    for n in notifications:
        print(
            f"  - ID={n.id} | recipient={n.recipient_id} | "
            f"type='{n.type}' | status='{n.status}' | "
            f"payload={n.payload} | created_at={n.created_at}"
        )
    print(f"{'=' * 70}\n")

    return {
        "assignee_id": task.assignee_id if task else None,
        "status": task.status.value if task else None,
        "history_count": len(history_records),
        "status_count": len(status_records),
        "activity_count": len(activity_records),
        "notification_count": len(notifications),
    }


async def main() -> None:
    engine = create_async_engine(str(settings.database_url))
    session_factory = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    async with session_factory() as session:
        print("\n STEP 1: Seeding Initial Data (Project, 2 Users, 1 Task)")
        project = Project(name="Phoenix Platform", description="Core modernization project")
        t = asyncio.get_event_loop().time()
        alice = User(name="Alice Lead", email=f"alice_{t}@example.com")
        bob = User(name="Bob Dev", email=f"bob_{t}@example.com")
        charlie = User(name="Charlie Dev", email=f"charlie_{t}@example.com")
        session.add_all([project, alice, bob, charlie])
        await session.commit()
        await session.refresh(project)
        await session.refresh(alice)
        await session.refresh(bob)
        await session.refresh(charlie)

        session.add_all(
            [
                ProjectUser(project_id=project.id, user_id=alice.id, role=ProjectRole.owner),
                ProjectUser(project_id=project.id, user_id=bob.id, role=ProjectRole.member),
                ProjectUser(project_id=project.id, user_id=charlie.id, role=ProjectRole.member),
            ]
        )
        await session.commit()

        task = Task(
            title="Implement Transaction Safety",
            description="Multi-table atomic writes",
            project_id=project.id,
            assignee_id=None,
            status=TaskStatus.todo,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        task_id = task.id

        # -------------------------------------------------------------
        # STEP 1: INITIAL STATE
        # -------------------------------------------------------------
        await print_db_snapshot(session, task_id, "INITIAL STATE (Unassigned Task)")

        # -------------------------------------------------------------
        # STEP 2: SUCCESSFUL TRANSACTION
        # -------------------------------------------------------------
        print("\n STEP 2: Executing Successful Task Assignment (Assigning to Bob)...")
        await TaskService.assign_task(
            session,
            task_id=task_id,
            data=TaskAssignRequest(
                assignee_id=bob.id,
                assigned_by_id=alice.id,
                status=TaskStatus.in_progress,
                simulate_failure=False,
            ),
        )
        snapshot_success = await print_db_snapshot(
            session, task_id, "AFTER SUCCESSFUL TRANSACTION (Bob Assigned)"
        )

        # -------------------------------------------------------------
        # STEP 3: FORCED FAILURE MIDWAY (ROLLBACK PROOF)
        # -------------------------------------------------------------
        print("\n STEP 3: Attempting Reassignment to Charlie with SIMULATED FAILURE...")
        try:
            await TaskService.assign_task(
                session,
                task_id=task_id,
                data=TaskAssignRequest(
                    assignee_id=charlie.id,
                    assigned_by_id=alice.id,
                    status=TaskStatus.done,
                    simulate_failure=True,
                ),
            )
            print(" Unexpected: No error raised!")
        except TransactionSimulationError as e:
            print(f" Expected Exception Caught: {e.message}")

        # Re-query DB to demonstrate complete rollback
        session.expire_all()
        snapshot_after_failure = await print_db_snapshot(
            session,
            task_id,
            "AFTER FORCED FAILURE (Rollback Proof: State Unchanged)",
        )

        # -------------------------------------------------------------
        # VERIFICATION REPORT (PASS/FAIL)
        # -------------------------------------------------------------
        print(f"\n{'=' * 70}")
        print(" TRANSACTION ROLLBACK VERIFICATION CHECKLIST")
        print(f"{'=' * 70}")

        checks = [
            (
                "Task Assignee Unchanged (Still Bob)",
                snapshot_after_failure["assignee_id"] == snapshot_success["assignee_id"],
            ),
            (
                "Task Status Unchanged (Still in_progress)",
                snapshot_after_failure["status"] == snapshot_success["status"],
            ),
            (
                "No Partial Assignment History Persisted",
                snapshot_after_failure["history_count"] == snapshot_success["history_count"],
            ),
            (
                "No Partial Status History Persisted",
                snapshot_after_failure["status_count"] == snapshot_success["status_count"],
            ),
            (
                "No Partial Activity Log Persisted",
                snapshot_after_failure["activity_count"] == snapshot_success["activity_count"],
            ),
            (
                "No Partial Notification Persisted",
                snapshot_after_failure["notification_count"]
                == snapshot_success["notification_count"],
            ),
        ]

        all_passed = True
        for name, passed in checks:
            status_str = " PASS" if passed else " FAIL"
            print(f"[{status_str}] {name}")
            if not passed:
                all_passed = False

        print(f"{'=' * 70}")
        if all_passed:
            print(" ALL ATOMICITY CHECKS PASSED: Rollback fully verified!")
        else:
            print(" ATOMICITY VERIFICATION FAILED!")
        print(f"{'=' * 70}\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
