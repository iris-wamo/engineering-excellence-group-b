"""End-to-end demonstration script for Celery Beat due-task reminders and Flower monitoring.

Demonstrates:
1. Due-date task matching (due soon vs far future vs completed vs unassigned).
2. Automated reminder generation into the notification table.
3. Concurrency overlap protection via Redis distributed locking.
4. Idempotent duplicate prevention (no spamming on consecutive scheduler ticks).
5. Celery Beat periodic schedule inspection and Flower connectivity.
"""

import asyncio
import sys
import time
from datetime import date, timedelta

import redis.asyncio as aioredis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.celery_app import celery_app
from app.core.config import settings
from app.models.enums import ProjectRole, TaskPriority, TaskStatus
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.models.user import User
from app.tasks.locks import acquire_redis_lock, release_redis_lock
from app.tasks.reminder_tasks import REMINDER_LOCK_KEY, _process_due_task_reminders


def banner(title: str) -> None:
    print(f"\n{'=' * 75}")
    print(f"  TaskFlow — Session 05 Demo: {title}")
    print(f"{'=' * 75}\n")


def step(title: str) -> None:
    print(f"\n>> {title}")


async def run_demo() -> None:
    banner("Celery Beat Due-Task Reminders & Overlap Prevention")

    # 1. Connect to Redis
    redis_client = aioredis.from_url(str(settings.redis_url), decode_responses=True)
    try:
        await redis_client.ping()
        print(f"[OK] Connected to Redis Broker at {settings.redis_url}")
    except Exception as exc:
        print(f"[FAIL] Could not connect to Redis: {exc}")
        sys.exit(1)

    # 2. Connect to Postgres
    engine = create_async_engine(str(settings.database_url))
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with sessionmaker() as db:
        try:
            res = await db.execute(select(func.current_database()))
            print(f"[OK] Connected to Postgres Database: /{res.scalar()}")
        except Exception as exc:
            print(f"[FAIL] Could not connect to Postgres: {exc}")
            sys.exit(1)

        # Ensure lock is clean
        await redis_client.delete(REMINDER_LOCK_KEY)

        # 3. Setup test data
        step("Setting up Test Tasks and Users for Due-Date Scenarios")
        user = await db.scalar(select(User).where(User.email == "beat.dev@example.com"))
        if not user:
            user = User(name="Beat Dev", email="beat.dev@example.com")
            db.add(user)
            await db.commit()
            await db.refresh(user)

        project = await db.scalar(select(Project).where(Project.slug == "beat-demo-project"))
        if not project:
            project = Project(
                name="Beat Demo Project",
                slug="beat-demo-project",
                workspace_id=1,
            )
            db.add(project)
            await db.commit()
            await db.refresh(project)
            pu = ProjectUser(project_id=project.id, user_id=user.id, role=ProjectRole.member)
            db.add(pu)
            await db.commit()

        # Clean old demo notifications and tasks
        await db.execute(
            delete(Notification).where(
                Notification.recipient_id == user.id,
                Notification.type == "TASK_DUE_REMINDER",
            )
        )
        await db.execute(
            delete(Task).where(
                Task.project_id == project.id,
                Task.title.like("Beat Test Task%"),
            )
        )
        await db.commit()

        today = date.today()

        # Task 1: Due Today, Incomplete, Assigned -> MUST RECEIVE REMINDER
        task_due_today = Task(
            title="Beat Test Task #1 - Due Today",
            description="Important deliverable due today",
            status=TaskStatus.in_progress,
            priority=TaskPriority.high,
            due_date=today,
            project_id=project.id,
            assignee_id=user.id,
            workspace_id=1,
        )
        # Task 2: Due in 30 days, Incomplete, Assigned -> SHOULD NOT RECEIVE REMINDER
        task_due_future = Task(
            title="Beat Test Task #2 - Far Future",
            description="Deliverable due in a month",
            status=TaskStatus.todo,
            priority=TaskPriority.medium,
            due_date=today + timedelta(days=30),
            project_id=project.id,
            assignee_id=user.id,
            workspace_id=1,
        )
        # Task 3: Due Today, Completed (done), Assigned -> SHOULD NOT RECEIVE REMINDER
        task_done = Task(
            title="Beat Test Task #3 - Already Done",
            description="Completed deliverable due today",
            status=TaskStatus.done,
            priority=TaskPriority.low,
            due_date=today,
            project_id=project.id,
            assignee_id=user.id,
            workspace_id=1,
        )
        # Task 4: Due Today, Incomplete, Unassigned -> SHOULD NOT RECEIVE REMINDER
        task_unassigned = Task(
            title="Beat Test Task #4 - Unassigned",
            description="Unassigned task due today",
            status=TaskStatus.todo,
            priority=TaskPriority.high,
            due_date=today,
            project_id=project.id,
            assignee_id=None,
            workspace_id=1,
        )
        db.add_all([task_due_today, task_due_future, task_done, task_unassigned])
        await db.commit()
        await db.refresh(task_due_today)

        print(f"  • Task 1 (ID={task_due_today.id}): Due TODAY, in_progress, assigned to {user.id}")
        print("  • Task 2: Due +30 days, todo, assigned")
        print("  • Task 3: Due TODAY, done, assigned")
        print("  • Task 4: Due TODAY, todo, unassigned")

        # Step 1: Run Initial Reminder Sweep
        step("Step 1: Execute Celery Beat Due-Task Reminder Sweep")
        t0 = time.perf_counter()
        result_sweep_1 = await _process_due_task_reminders(
            threshold_days=1,
            db=db,
            redis_client=redis_client,
        )
        latency = (time.perf_counter() - t0) * 1000

        print(f"  • Sweep completed in {latency:.2f} ms")
        print(f"  • Result metrics: {result_sweep_1}")

        assert result_sweep_1["status"] == "success"
        assert result_sweep_1["reminders_created"] == 1
        assert task_due_today.id in result_sweep_1["reminded_task_ids"]

        # Verify DB row
        notif = (
            await db.scalars(
                select(Notification).where(
                    Notification.task_id == task_due_today.id,
                    Notification.type == "TASK_DUE_REMINDER",
                )
            )
        ).first()
        assert notif is not None
        print(
            f"  • Verified Notification in DB: ID={notif.id}, Type={notif.type}, "
            f"Status={notif.status}"
        )
        print(f"  • Stored Payload: {notif.payload}")
        print("  [PASS] Exactly 1 reminder generated for the qualified due task.")

        # Step 2: Overlapping Run Prevention (Redis Distributed Lock)
        step("Step 2: Simulate Overlapping Scheduler Run (Redis Lock Overlap Check)")
        print("  Acquiring Redis lock artificially to simulate another long-running sweep...")
        lock_token = await acquire_redis_lock(redis_client, REMINDER_LOCK_KEY, timeout_seconds=60)
        assert lock_token is not None
        print(f"  • Active Lock Key '{REMINDER_LOCK_KEY}' held with token {lock_token[:8]}...")

        print("  Attempting concurrent sweep while lock is active...")
        result_overlap = await _process_due_task_reminders(
            threshold_days=1,
            db=db,
            redis_client=redis_client,
        )
        print(f"  • Concurrent Sweep Response: {result_overlap}")
        assert result_overlap["status"] == "skipped"
        assert result_overlap["reason"] == "overlapping_run"
        print("  [PASS] Overlapping run was rejected immediately without duplicate work.")

        # Release artificial lock
        released = await release_redis_lock(redis_client, REMINDER_LOCK_KEY, lock_token)
        assert released
        print("  • Released simulated lock successfully.")

        # Step 3: Idempotency & Deduplication Check
        step("Step 3: Consecutive Sweep Deduplication Check (No Duplicate Reminders)")
        print("  Running sweep again with lock released...")
        result_sweep_2 = await _process_due_task_reminders(
            threshold_days=1,
            db=db,
            redis_client=redis_client,
        )
        print(f"  • Second Sweep Response: {result_sweep_2}")
        assert result_sweep_2["status"] == "success"
        assert result_sweep_2["reminders_created"] == 0
        assert result_sweep_2["reminders_skipped"] >= 1

        # Check total notifications in DB
        total_notifs = (
            await db.scalars(
                select(Notification).where(
                    Notification.task_id == task_due_today.id,
                    Notification.type == "TASK_DUE_REMINDER",
                )
            )
        ).all()
        assert len(total_notifs) == 1
        print(f"  • Total DB notifications for task {task_due_today.id}: {len(total_notifs)}")
        print("  [PASS] Zero duplicate notifications created on subsequent sweep.")

        # Step 4: Beat Schedule Configuration & Flower Overview
        step("Step 4: Inspect Celery Beat Schedule & Flower Observability")
        beat_schedule = celery_app.conf.beat_schedule
        print("  • Registered Celery Beat Periodic Jobs:")
        for job_name, config in beat_schedule.items():
            print(f"    - '{job_name}': task={config['task']}, schedule={config['schedule']}s")

        print("\n  • Flower Observability Service:")
        print(f"    - URL: http://localhost:{settings.flower_port}")
        print("    - Capabilities: Worker heartbeats, active tasks, retries, periodic schedules")

    await redis_client.aclose()
    await engine.dispose()

    banner("All Celery Beat & Due Reminder Behaviors Verified Successfully!")


if __name__ == "__main__":
    asyncio.run(run_demo())
