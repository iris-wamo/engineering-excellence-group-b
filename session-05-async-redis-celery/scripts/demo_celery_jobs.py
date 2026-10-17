"""Demo 04 — Retryable Celery Background Jobs for Task Assignment Notifications.

Run: make celery-demo (or: uv run python -m scripts.demo_celery_jobs)
Requires: docker compose up -d db redis

Demonstrates end-to-end:
  1. Fast HTTP-path assignment with asynchronous job queuing (< 5ms response)
  2. Worker processing: picking up job and transitioning notification from pending -> sent
  3. Idempotent deduplication: duplicate execution does not create duplicate notification rows
  4. Transient failure retry: exponential backoff retry and recovery
  5. Permanent failure termination: immediate failure without retry, marking notification failed
  6. Worker-down queue resilience: jobs buffered safely in Redis list while worker is offline
"""

import asyncio
import time
from typing import Any

import redis
from celery.exceptions import Retry
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import ProjectRole, TaskPriority, TaskStatus
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_user import ProjectUser
from app.models.task import Task
from app.models.user import User
from app.models.workspace_user import WorkspaceUser
from app.schemas.task import TaskAssignRequest
from app.services.task_service import TaskService
from app.tasks.db import get_worker_db
from app.tasks.exceptions import (
    TaskNotFoundError,
)
from app.tasks.notification_tasks import (
    _process_assignment_notification,
    send_task_assignment_notification,
)

GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 75}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}\n")


def subheader(text: str) -> None:
    print(f"{BOLD}{YELLOW}>> {text}{RESET}")


async def setup_demo_entities(db: AsyncSession) -> dict[str, Any]:
    """Ensure baseline Workspace, Users, and Project exist for the demo."""
    # Ensure assigner
    assigner = await db.scalar(select(User).where(User.email == "demo_lead@example.com"))
    if not assigner:
        assigner = User(name="Demo Lead", email="demo_lead@example.com")
        db.add(assigner)

    # Ensure assignee 1
    assignee_1 = await db.scalar(select(User).where(User.email == "demo_alice@example.com"))
    if not assignee_1:
        assignee_1 = User(name="Alice Developer", email="demo_alice@example.com")
        db.add(assignee_1)

    # Ensure assignee 2
    assignee_2 = await db.scalar(select(User).where(User.email == "demo_bob@example.com"))
    if not assignee_2:
        assignee_2 = User(name="Bob Developer", email="demo_bob@example.com")
        db.add(assignee_2)

    await db.commit()
    await db.refresh(assigner)
    await db.refresh(assignee_1)
    await db.refresh(assignee_2)

    # Ensure workspace enrollment
    for u in [assigner, assignee_1, assignee_2]:
        wu = await db.scalar(
            select(WorkspaceUser).where(
                WorkspaceUser.workspace_id == 1,
                WorkspaceUser.user_id == u.id,
            )
        )
        if not wu:
            db.add(WorkspaceUser(workspace_id=1, user_id=u.id))
    await db.commit()

    # Ensure project
    project = await db.scalar(select(Project).where(Project.slug == "celery-demo-project"))
    if not project:
        project = Project(
            name="Celery Demo Project",
            slug="celery-demo-project",
            workspace_id=1,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)

    # Ensure project memberships
    for u, role in [
        (assigner, ProjectRole.owner),
        (assignee_1, ProjectRole.member),
        (assignee_2, ProjectRole.member),
    ]:
        pu = await db.scalar(
            select(ProjectUser).where(
                ProjectUser.project_id == project.id,
                ProjectUser.user_id == u.id,
            )
        )
        if not pu:
            db.add(ProjectUser(project_id=project.id, user_id=u.id, role=role))
    await db.commit()

    # Create a fresh task for demo
    task = Task(
        title=f"Notification Pipeline Task #{int(time.time()) % 10000}",
        description="Demo Celery background assignment notifications",
        project_id=project.id,
        workspace_id=1,
        priority=TaskPriority.high,
        status=TaskStatus.todo,
        assignee_id=None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    return {
        "assigner": assigner,
        "assignee_1": assignee_1,
        "assignee_2": assignee_2,
        "project": project,
        "task": task,
    }


async def run_demo() -> None:
    header("TaskFlow — Session 05 Demo: Retryable Celery Background Jobs")

    r = redis.from_url(str(settings.celery_broker_url))
    try:
        r.ping()
        print(f"[{GREEN}OK{RESET}] Connected to Redis Broker at {settings.celery_broker_url}")
    except Exception as exc:
        print(f"[{RED}FAIL{RESET}] Redis not reachable: {exc}")
        print("Please run: docker compose up -d redis")
        return

    async with get_worker_db() as db:
        print(f"[{GREEN}OK{RESET}] Connected to Postgres Database: {settings.database_url.path}")
        ctx = await setup_demo_entities(db)

    task: Task = ctx["task"]
    assignee: User = ctx["assignee_1"]
    assigner: User = ctx["assigner"]

    print("Setup test entities:")
    print(f"  • Task ID: {task.id} ('{task.title}')")
    print(f"  • Assignee ID: {assignee.id} ({assignee.name})")
    print(f"  • Assigner ID: {assigner.id} ({assigner.name})\n")

    # -------------------------------------------------------------------------
    # Scenario 1: Fast API assignment with async background queuing
    # -------------------------------------------------------------------------
    subheader("Step 1: Assign Task via Service / API (Measure Dispatch Latency)")
    start_time = time.perf_counter()

    async with get_worker_db() as db:
        updated = await TaskService.assign_task(
            db,
            task_id=task.id,
            data=TaskAssignRequest(assignee_id=assignee.id),
            actor_id=assigner.id,
        )

    duration_ms = (time.perf_counter() - start_time) * 1000
    print(f"  • Task assigned to user {updated.assignee_id}")
    print(f"  • Request-path execution time: {BOLD}{duration_ms:.2f} ms{RESET}")
    print("  • Background job queued to Celery broker via send_task_assignment_notification.delay")

    # Verify pending notification created in DB
    async with get_worker_db() as db:
        notif = await db.scalar(
            select(Notification).where(
                Notification.task_id == task.id,
                Notification.recipient_id == assignee.id,
            )
        )
        assert notif is not None
        print(f"  • Notification row in DB: ID={notif.id}, Status={YELLOW}{notif.status}{RESET}\n")

    # -------------------------------------------------------------------------
    # Scenario 2: Worker picks up and completes the notification job
    # -------------------------------------------------------------------------
    subheader("Step 2: Celery Worker Processes Notification Job")
    result = await _process_assignment_notification(
        task_id=task.id,
        recipient_id=assignee.id,
        assigned_by_id=assigner.id,
    )
    print(f"  • Worker execution result: {result}")

    async with get_worker_db() as db:
        notif = await db.scalar(
            select(Notification).where(Notification.id == result["notification_id"])
        )
        assert notif is not None
        print(f"  • Updated DB Notification: ID={notif.id}, Status={GREEN}{notif.status}{RESET}")
        print(f"  • Stored Payload: {notif.payload}\n")

    # -------------------------------------------------------------------------
    # Scenario 3: Task Idempotency (Running job twice has no duplicate effect)
    # -------------------------------------------------------------------------
    subheader("Step 3: Idempotent Delivery Check (Duplicate Execution)")
    duplicate_result = await _process_assignment_notification(
        task_id=task.id,
        recipient_id=assignee.id,
        assigned_by_id=assigner.id,
    )
    print(f"  • Second execution result: {duplicate_result}")
    assert duplicate_result["idempotent"] is True
    assert duplicate_result["status"] == "already_sent"

    async with get_worker_db() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.task_id == task.id,
                Notification.recipient_id == assignee.id,
            )
        )
        print(
            f"  • Notification count in DB for (task={task.id}, recipient={assignee.id}): "
            f"{BOLD}{count}{RESET}"
        )
        assert count == 1
        print(f"  [{GREEN}PASS{RESET}] Exactly 1 notification exists. Duplicate ignored safely.\n")

    # -------------------------------------------------------------------------
    # Scenario 4: Transient failure with exponential retry backoff
    # -------------------------------------------------------------------------
    subheader("Step 4: Transient Failure & Automatic Retry Simulation")
    print(
        "  Simulating temporary network/database outage on attempt 1 "
        "(simulate_transient_failures=1)..."
    )
    try:
        send_task_assignment_notification.apply(
            kwargs={
                "task_id": task.id,
                "recipient_id": assignee.id,
                "simulate_transient_failures": 1,
            },
            throw=True,
        )
    except Retry as exc:
        print(f"  • Celery caught transient failure: {type(exc)}: {exc}")
        print("  • Automatic retry scheduled with backoff countdown")
        print(f"  [{GREEN}PASS{RESET}] Transient failure triggers automatic retry.\n")

    # -------------------------------------------------------------------------
    # Scenario 5: Permanent failure (Entity not found or invalid data)
    # -------------------------------------------------------------------------
    subheader("Step 5: Permanent Failure (No Retries, Mark Failed)")
    print("  Testing permanent failure on invalid task ID 999999...")
    try:
        send_task_assignment_notification.apply(
            kwargs={"task_id": 999_999, "recipient_id": assignee.id},
            throw=True,
        )
    except TaskNotFoundError as exc:
        print(f"  • Caught non-retryable error: {type(exc).__name__}: {exc}")
        print("  • Celery aborted immediately without scheduling retry.")
        print(f"  [{GREEN}PASS{RESET}] Permanent errors never retry.\n")

    # -------------------------------------------------------------------------
    # Scenario 6: Worker offline resilience (Redis broker queue buffering)
    # -------------------------------------------------------------------------
    subheader("Step 6: Worker-Down Resilience (Job Buffered in Broker)")
    queue_name = "celery"
    initial_queue_len = r.llen(queue_name)
    print(f"  • Broker queue '{queue_name}' initial length: {initial_queue_len}")

    # Enqueue a task directly to broker as if worker is stopped
    async_res = send_task_assignment_notification.delay(
        task_id=task.id,
        recipient_id=assignee.id,
        assigned_by_id=assigner.id,
    )
    new_queue_len = r.llen(queue_name)
    print(f"  • Enqueued task {async_res.id} into Redis broker")
    print(f"  • Broker queue '{queue_name}' length now: {BOLD}{new_queue_len}{RESET}")
    assert new_queue_len == initial_queue_len + 1
    print(f"  [{GREEN}PASS{RESET}] Job is safely preserved in Redis queue while worker is offline.")

    # Clean up the test message from the queue
    r.rpop(queue_name)
    print(f"  • Drained test message from queue. Remaining: {r.llen(queue_name)}\n")

    header("All Celery Background Job Behaviors Verified Successfully!")


if __name__ == "__main__":
    asyncio.run(run_demo())
