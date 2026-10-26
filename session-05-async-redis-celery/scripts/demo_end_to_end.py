"""End-to-end demonstration: one task change through the whole Session 05 stack.

Drives the running Docker stack (`make docker-up`) over HTTP, the way a client would, and
checks each part of the flow from the outside:

1. Every service answers: api, Redis, a Celery worker, and Flower.
2. The task summary is served from the Redis cache on a repeat read.
3. Assigning the task responds quickly, invalidates the cached summary, appends a
   task.assigned event to the Redis Stream, and the Celery worker delivers the assignment
   notification from the outbox.
4. Starting the task appends a task.status_changed event and invalidates the cache again.
5. Celery Beat's due-task sweep reminds the assignee, because the task is due today.
6. Flower recorded the notification job and the reminder sweep.

The users, project and task it creates are real rows (the API writes them), kept so they
can be inspected afterwards. Emails carry a random suffix, so the demo can run again.
See docs/session-05/end-to-end-flow.md.
"""

import ast
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from dotenv import dotenv_values
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.cache.task_summary_cache import summary_key, version_key
from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.redis import create_redis_client
from app.models.enums import ProjectRole
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_user import ProjectUser

API_URL = os.environ.get("API_URL", "http://localhost:8000")
FLOWER_URL = f"http://127.0.0.1:{settings.flower_port}"
WORKSPACE_ID = 1  # requests without X-Workspace-ID use the default workspace
PASSWORD = "password123"
NOTIFICATION_TIMEOUT_SECONDS = 30.0
# One Beat interval plus time for the worker to run the sweep
REMINDER_TIMEOUT_SECONDS = settings.due_reminder_interval_seconds + 30.0
# Recent jobs per task name fetched from Flower, newest first
FLOWER_TASK_WINDOW = 100

failures: list[str] = []


def banner(title: str) -> None:
    print(f"\n{'=' * 75}")
    print(f"  TaskFlow — Session 05 Demo: {title}")
    print(f"{'=' * 75}\n")


def step(title: str) -> None:
    print(f"\n>> {title}")


def check(passed: bool, message: str) -> bool:
    print(f"  [{'PASS' if passed else 'FAIL'}] {message}")
    if not passed:
        failures.append(message)
    return passed


def flower_auth() -> tuple[str, str] | None:
    """The FLOWER_BASIC_AUTH login from the environment or .env, if set."""
    value = os.environ.get("FLOWER_BASIC_AUTH") or dotenv_values(".env").get("FLOWER_BASIC_AUTH")
    if not value or ":" not in value:
        return None
    user, password = value.split(",")[0].split(":", 1)
    return user, password


async def cache_version(redis: Redis) -> int:
    raw = await redis.get(version_key(WORKSPACE_ID))
    return int(raw) if raw is not None else 0


async def last_stream_id(redis: Redis) -> str:
    entries = cast(
        list[tuple[str, dict[str, str]]],
        await redis.xrevrange(settings.task_events_stream, count=1),
    )
    return entries[0][0] if entries else "0-0"


async def stream_events_since(redis: Redis, after_id: str, task_id: int) -> list[dict[str, Any]]:
    """Stream entries for task_id appended after after_id, oldest first."""
    entries = cast(
        list[tuple[str, dict[str, str]]],
        await redis.xrange(settings.task_events_stream, min=f"({after_id}", max="+"),
    )
    events = []
    for entry_id, fields in entries:
        if json.loads(fields.get("payload", "{}")).get("task_id") == task_id:
            events.append({"id": entry_id, "event_type": fields.get("event_type")})
    return events


async def wait_for_notification(
    engine: AsyncEngine,
    task_id: int,
    notification_type: str,
    timeout: float,
    status: str | None = None,
) -> Notification | None:
    """Poll Postgres until a notification of this type exists for the task (and has status)."""
    deadline = time.monotonic() + timeout
    while True:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            stmt = select(Notification).where(
                Notification.task_id == task_id, Notification.type == notification_type
            )
            if status is not None:
                stmt = stmt.where(Notification.status == status)
            notification = (await db.scalars(stmt.order_by(Notification.id.desc()))).first()
        if notification is not None or time.monotonic() >= deadline:
            return notification
        await asyncio.sleep(1)


async def timed(request: Any) -> tuple[httpx.Response, float]:
    t0 = time.perf_counter()
    response = await request
    return response, (time.perf_counter() - t0) * 1000


async def preflight(api: httpx.AsyncClient, redis: Redis) -> None:
    step("Step 0: Check that every service in the flow is up")
    try:
        docs = await api.get("/docs")
        check(docs.status_code == 200, f"api answers at {API_URL}")
    except httpx.HTTPError as exc:
        check(False, f"api at {API_URL} is unreachable ({exc}); run `make docker-up`")
        raise SystemExit(1) from exc

    try:
        check(bool(await redis.ping()), f"Redis answers at {settings.redis_url}")
    except Exception as exc:
        check(False, f"Redis at {settings.redis_url} is unreachable ({exc})")
        raise SystemExit(1) from exc

    try:
        replies = await asyncio.to_thread(celery_app.control.ping, timeout=2.0)
    except Exception as exc:
        check(False, f"Celery broker at {settings.celery_broker_url} is unreachable ({exc})")
        raise SystemExit(1) from exc
    workers = [name for reply in replies for name in reply]
    check(bool(workers), f"Celery worker online: {', '.join(workers) or 'none'}")

    auth = flower_auth()
    if auth is None:
        print("  [SKIP] FLOWER_BASIC_AUTH is not set, so the Flower checks are skipped")
        return
    try:
        async with httpx.AsyncClient(base_url=FLOWER_URL, auth=auth, timeout=5) as flower:
            response = await flower.get("/api/workers", params={"refresh": "true"})
        check(response.status_code == 200, f"Flower answers at {FLOWER_URL}")
    except httpx.HTTPError as exc:
        check(False, f"Flower at {FLOWER_URL} is unreachable ({exc})")


async def setup(api: httpx.AsyncClient, engine: AsyncEngine) -> dict[str, Any]:
    step("Step 1: Create a manager, a developer, a project, and a task due today")
    suffix = uuid.uuid4().hex[:8]
    users: dict[str, dict[str, Any]] = {}
    for key, name in (("manager", "Maya Manager"), ("developer", "Dev Dana")):
        email = f"flow.{key}.{suffix}@example.com"
        signup = await api.post(
            "/api/v1/auth/signup", json={"name": name, "email": email, "password": PASSWORD}
        )
        signup.raise_for_status()
        login = await api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        login.raise_for_status()
        users[key] = {
            "id": signup.json()["id"],
            "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        }

    # POST /projects needs an admin, and the admin role needs an existing project, so the
    # project and its two roles are inserted directly (as in the Redis events demo).
    async with AsyncSession(engine, expire_on_commit=False) as db:
        project = Project(
            name=f"Flow Demo {suffix}", slug=f"flow-demo-{suffix}", workspace_id=WORKSPACE_ID
        )
        db.add(project)
        await db.flush()
        db.add_all(
            [
                ProjectUser(
                    project_id=project.id,
                    user_id=users["manager"]["id"],
                    role=ProjectRole.manager,
                ),
                ProjectUser(
                    project_id=project.id,
                    user_id=users["developer"]["id"],
                    role=ProjectRole.member,
                ),
            ]
        )
        await db.commit()
        project_id = project.id

    # The reminder sweep compares due dates with the UTC calendar day
    today = datetime.now(UTC).date()
    created = await api.post(
        "/api/v1/tasks",
        headers=users["manager"]["headers"],
        json={
            "title": f"Ship the flow demo {suffix}",
            "project_id": project_id,
            "due_date": today.isoformat(),
        },
    )
    created.raise_for_status()
    task_id = created.json()["id"]

    print(
        f"  • manager={users['manager']['id']} developer={users['developer']['id']} "
        f"project={project_id} task={task_id} (due {today})"
    )
    return {"users": users, "project_id": project_id, "task_id": task_id}


async def show_cache(api: httpx.AsyncClient, redis: Redis) -> None:
    step("Step 2: Read the task summary twice (cache miss, then hit)")
    first, first_ms = await timed(api.get("/api/v1/tasks/summary"))
    first.raise_for_status()
    key = summary_key(WORKSPACE_ID, await cache_version(redis))
    ttl_after_first = await redis.pttl(key)
    second, second_ms = await timed(api.get("/api/v1/tasks/summary"))
    second.raise_for_status()
    ttl_after_second = await redis.pttl(key)

    print(
        f"  • 1st read {first_ms:.0f} ms, 2nd read {second_ms:.0f} ms "
        "(both include the simulated 200 ms external call, which is never cached)"
    )
    check(ttl_after_first > 0, f"1st read stored the summary at {key} (TTL {ttl_after_first} ms)")
    # A miss stores the entry again and resets its TTL; a hit only reads it, so the TTL
    # keeps counting down.
    check(
        0 < ttl_after_second < ttl_after_first,
        f"2nd read was a cache hit (TTL {ttl_after_first} -> {ttl_after_second} ms, not reset)",
    )
    # external_service is the live per-request call; only the metrics come from the cache
    first_metrics = {k: v for k, v in first.json().items() if k != "external_service"}
    second_metrics = {k: v for k, v in second.json().items() if k != "external_service"}
    check(first_metrics == second_metrics, "2nd read returned the same metrics")
    print(
        f"  • api log lines: request {first.headers.get('x-request-id')} (MISS), "
        f"{second.headers.get('x-request-id')} (HIT)"
    )


async def assign(
    api: httpx.AsyncClient, redis: Redis, engine: AsyncEngine, ctx: dict[str, Any]
) -> int:
    step("Step 3: Manager assigns the task to the developer")
    task_id = ctx["task_id"]
    developer_id = ctx["users"]["developer"]["id"]
    version_before = await cache_version(redis)
    stream_before = await last_stream_id(redis)

    response, elapsed_ms = await timed(
        api.post(
            f"/api/v1/tasks/{task_id}/assign",
            headers=ctx["users"]["manager"]["headers"],
            json={"assignee_id": developer_id},
        )
    )
    request_id = response.headers.get("x-request-id", "-")
    check(
        response.status_code == 200,
        f"API responded {response.status_code} in {elapsed_ms:.0f} ms (request id {request_id})",
    )

    version_after = await cache_version(redis)
    check(
        version_after > version_before,
        f"summary cache invalidated ({version_key(WORKSPACE_ID)} "
        f"{version_before} -> {version_after})",
    )

    events = await stream_events_since(redis, stream_before, task_id)
    check(
        any(e["event_type"] == "task.assigned" for e in events),
        f"task.assigned appended to {settings.task_events_stream}: {events}",
    )

    print(f"  • Waiting up to {NOTIFICATION_TIMEOUT_SECONDS:.0f}s for the worker to deliver...")
    t0 = time.monotonic()
    notification = await wait_for_notification(
        engine, task_id, "TASK_ASSIGNED", NOTIFICATION_TIMEOUT_SECONDS, status="sent"
    )
    if check(notification is not None, "Celery worker delivered the assignment notification"):
        assert notification is not None
        print(
            f"  • notification id={notification.id} status={notification.status} "
            f"recipient={notification.recipient_id}, "
            f"{time.monotonic() - t0:.1f}s after the API responded"
        )
        return notification.id
    return 0


async def start_work(api: httpx.AsyncClient, redis: Redis, ctx: dict[str, Any]) -> None:
    step("Step 4: Developer starts the task (todo -> in_progress)")
    task_id = ctx["task_id"]
    version_before = await cache_version(redis)
    stream_before = await last_stream_id(redis)

    response, elapsed_ms = await timed(
        api.patch(
            f"/api/v1/tasks/{task_id}/status",
            headers=ctx["users"]["developer"]["headers"],
            json={"status": "in_progress"},
        )
    )
    check(
        response.status_code == 200, f"API responded {response.status_code} in {elapsed_ms:.0f} ms"
    )
    check(await cache_version(redis) > version_before, "summary cache invalidated again")
    events = await stream_events_since(redis, stream_before, task_id)
    check(
        any(e["event_type"] == "task.status_changed" for e in events),
        f"task.status_changed appended to the stream: {events}",
    )


async def wait_for_reminder(engine: AsyncEngine, ctx: dict[str, Any]) -> None:
    step("Step 5: Celery Beat's due-task sweep reminds the assignee")
    print(
        f"  • Beat queues the sweep every {settings.due_reminder_interval_seconds:.0f}s; "
        f"waiting up to {REMINDER_TIMEOUT_SECONDS:.0f}s..."
    )
    t0 = time.monotonic()
    reminder = await wait_for_notification(
        engine, ctx["task_id"], "TASK_DUE_REMINDER", REMINDER_TIMEOUT_SECONDS
    )
    if check(reminder is not None, "TASK_DUE_REMINDER created for the task due today"):
        assert reminder is not None
        print(
            f"  • reminder id={reminder.id} recipient={reminder.recipient_id} "
            f"after {time.monotonic() - t0:.0f}s, payload={reminder.payload}"
        )


def flower_value(raw: Any) -> Any:
    """Flower reports a job's kwargs and result as Python reprs; parse one back."""
    if not isinstance(raw, str):
        return raw
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None


async def flower_jobs(
    flower: httpx.AsyncClient, task_name: str, state: str | None = None
) -> dict[str, dict[str, Any]]:
    """The most recent jobs of one task name that Flower holds, newest first."""
    params: dict[str, Any] = {
        "taskname": task_name,
        "sort_by": "-received",
        "limit": FLOWER_TASK_WINDOW,
    }
    if state is not None:
        params["state"] = state
    response = await flower.get("/api/tasks", params=params)
    response.raise_for_status()
    return cast(dict[str, dict[str, Any]], response.json())


async def check_flower(notification_id: int, task_id: int) -> None:
    step("Step 6: Flower shows the jobs behind the flow")
    auth = flower_auth()
    if auth is None:
        print("  [SKIP] FLOWER_BASIC_AUTH is not set")
        return
    try:
        async with httpx.AsyncClient(base_url=FLOWER_URL, auth=auth, timeout=5) as flower:
            deliveries = await flower_jobs(
                flower, "app.tasks.notification_tasks.send_task_assignment_notification"
            )
            sweeps = await flower_jobs(
                flower, "app.tasks.reminder_tasks.send_due_task_reminders", state="SUCCESS"
            )
    except (httpx.HTTPError, ValueError) as exc:
        check(False, f"Could not read job history from Flower at {FLOWER_URL} ({exc})")
        return

    delivery = next(
        (
            (job_id, info)
            for job_id, info in deliveries.items()
            if (flower_value(info.get("kwargs")) or {}).get("notification_id") == notification_id
        ),
        None,
    )
    state = delivery[1].get("state") if delivery else None
    if check(
        state == "SUCCESS",
        f"Flower lists the delivery job for notification {notification_id} as succeeded "
        f"(state {state})",
    ):
        assert delivery is not None
        print(f"  • {FLOWER_URL}/task/{delivery[0]}")

    sweep = next(
        (
            (job_id, info)
            for job_id, info in sweeps.items()
            if task_id in (flower_value(info.get("result")) or {}).get("reminded_task_ids", [])
        ),
        None,
    )
    if check(sweep is not None, f"Flower lists the reminder sweep that reminded task {task_id}"):
        assert sweep is not None
        print(f"  • {FLOWER_URL}/task/{sweep[0]} result={sweep[1].get('result')}")


async def run_demo() -> None:
    banner("End-to-End Task Change: API -> Redis -> Celery -> Beat -> Flower")
    redis = create_redis_client()
    engine = create_async_engine(str(settings.database_url))
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=10) as api:
            await preflight(api, redis)
            ctx = await setup(api, engine)
            await show_cache(api, redis)
            notification_id = await assign(api, redis, engine, ctx)
            await start_work(api, redis, ctx)
            await wait_for_reminder(engine, ctx)
            await check_flower(notification_id, ctx["task_id"])
    finally:
        await redis.aclose()
        await engine.dispose()

    print(
        "\n  • Follow the same request id through `make docker-logs s=api` and "
        "`make docker-logs s=celery-worker`."
    )
    if failures:
        banner(f"{len(failures)} check(s) failed")
        for message in failures:
            print(f"  - {message}")
        sys.exit(1)
    banner("Every part of the flow handled the task change")


if __name__ == "__main__":
    asyncio.run(run_demo())
