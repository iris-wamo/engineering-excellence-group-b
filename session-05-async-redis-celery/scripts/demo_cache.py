"""Demonstration: Redis caching of GET /api/v1/tasks/summary and its invalidation.

Shows, against the dev database and Redis, a cache miss, a hit, the cache being cleared
by a task write, and expiry after the TTL. It creates one task in workspace 1 and deletes
it again at the end.

Requires a seeded dev DB with at least workspace 1, one project in it, and user 1,
because AUTH_HEADERS mints a token for user 1.
"""

import asyncio
import logging
import time

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from taskflow_shared.logging import configure_logging

from app.auth.security import create_access_token
from app.cache.task_summary_cache import invalidate_summary, summary_key, version_key
from app.core.config import settings
from app.db.redis import create_redis_client
from app.db.session import get_db
from app.main import app
from app.models.project import Project
from app.models.task import Task
from app.schemas.task import TaskCreate
from app.services.task_service import TaskService

WORKSPACE_ID = 1
SUMMARY_URL = "/api/v1/tasks/summary?external_delay=0.0"
AUTH_HEADERS = {
    "Authorization": f"Bearer {create_access_token(1)}",
    "X-Workspace-ID": str(WORKSPACE_ID),
}
DEMO_TTL_SECONDS = 3

logger = logging.getLogger("demo")


def heading(text: str) -> None:
    print(f"\n{'=' * 70}\n {text}\n{'=' * 70}")


async def show_redis(label: str) -> None:
    redis = create_redis_client()
    try:
        version = await redis.get(version_key(WORKSPACE_ID))
        current = int(version) if version is not None else 0
        key = summary_key(WORKSPACE_ID, current)
        print(f"  redis> GET {version_key(WORKSPACE_ID)}  ->  {version!r}")
        print(f"  redis> TTL {key}  ->  {await redis.ttl(key)}   ({label})")
    finally:
        await redis.aclose()


async def timed_summary(client: AsyncClient) -> None:
    start = time.perf_counter()
    response = await client.get(SUMMARY_URL, headers=AUTH_HEADERS)
    elapsed_ms = (time.perf_counter() - start) * 1000
    body = response.json()
    print(
        f"  GET /tasks/summary -> {response.status_code} in {elapsed_ms:.1f} ms  "
        f"total_count={body['total_count']} todo={body['counts_by_status']['todo']}"
    )


async def main() -> None:
    configure_logging(level=logging.INFO)
    settings.task_summary_cache_ttl_seconds = DEMO_TTL_SECONDS
    redis = create_redis_client()
    await redis.delete(version_key(WORKSPACE_ID))
    async for db in get_db():
        project_id = (
            (await db.execute(select(Project.id).where(Project.workspace_id == WORKSPACE_ID)))
            .scalars()
            .first()
        )
        if project_id is None:
            raise SystemExit("Seed the dev database first: no project in workspace 1.")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            heading("1. MISS, then HIT")
            await redis.delete(summary_key(WORKSPACE_ID, 0))
            await timed_summary(client)
            await show_redis("filled by the miss")
            await timed_summary(client)

            heading("2. A task write clears the cache")
            task = await TaskService.create_task(
                db, TaskCreate(title="cache demo task", project_id=project_id), WORKSPACE_ID
            )
            await show_redis("version bumped, new entry not written yet")
            await timed_summary(client)

            heading(f"3. Expiry after the {DEMO_TTL_SECONDS}s TTL")
            await timed_summary(client)
            print(f"  sleeping {DEMO_TTL_SECONDS + 1}s ...")
            await asyncio.sleep(DEMO_TTL_SECONDS + 1)
            await show_redis("expired")
            await timed_summary(client)

            heading("Cleanup")
            await db.execute(delete(Task).where(Task.id == task.id))
            await db.commit()
            await invalidate_summary(WORKSPACE_ID)
            print(f"  deleted demo task {task.id}")
    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
