"""Measure N+1 queries on the task-list endpoint.

Check 1: Real endpoint.
Check 2: Forced lazy loading.
Check 3: selectinload() fix.

Checks 2-3 are demonstration code and are not part of the application.
"""

import asyncio
import contextlib
from collections import Counter
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.services.task_service import TaskService

PAGE_SIZE = 100


class SQLCounter:
    def __init__(self, engine: AsyncEngine) -> None:
        self.statements: list[str] = []
        self.recording = False
        event.listen(engine.sync_engine, "before_cursor_execute", self._count)

    def _count(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if self.recording:
            self.statements.append(" ".join(statement.split()))

    @contextlib.contextmanager
    def record(self) -> Iterator[None]:
        self.statements = []
        self.recording = True
        try:
            yield
        finally:
            self.recording = False

    @property
    def count(self) -> int:
        return len(self.statements)

    def print_sql(self) -> None:
        for sql, count in Counter(self.statements).items():
            sql = sql if len(sql) <= 260 else sql[:260] + " ..."
            print(f"    [ran {count}x] {sql}")


engine = create_async_engine(str(settings.database_url))
counter = SQLCounter(engine)

SessionFactory = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


@contextlib.asynccontextmanager
async def new_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def load_tasks(session: AsyncSession) -> Sequence[Task]:
    tasks, _ = await TaskRepository.get_all(
        session,
        page=1,
        page_size=PAGE_SIZE,
        status=None,
        priority=None,
        project_id=None,
        assignee_id=None,
    )
    return tasks


def read_project(session: Session, tasks: Sequence[Task]) -> None:
    for task in tasks:
        _ = task.project.name


def read_project_and_assignee(session: Session, tasks: Sequence[Task]) -> None:
    for task in tasks:
        _ = task.project.name
        _ = task.assignee.name if task.assignee else None


def heading(title: str) -> None:
    print(f"\n{'=' * 76}\n{title}\n{'=' * 76}")


async def check_1() -> tuple[int, int]:
    heading("CHECK 1 — Real endpoint")

    results = []

    for page_size in (10, PAGE_SIZE):
        async with new_session() as session:
            with counter.record():
                response = await TaskService.list_tasks(
                    session,
                    page=1,
                    page_size=page_size,
                )

        print(f"  {len(response.items):>4} tasks -> {counter.count} SQL statements")
        results.append(counter.count)

    counter.print_sql()

    small, large = results

    if small == large:
        print(f"\n  Query count stayed the same: {small} -> {large}")
        print("  VERDICT: no N+1.")
    else:
        print(f"\n  Query count increased: {small} -> {large}")
        print("  VERDICT: possible N+1.")

    return small, large


async def check_2() -> tuple[int, int]:
    heading("CHECK 2 — Forced relationship access")

    async with new_session() as session:
        tasks = await load_tasks(session)
        projects = len({task.project_id for task in tasks})

        with counter.record():
            await session.run_sync(read_project, tasks)

    project_queries = counter.count

    print(f"  Reading project for {len(tasks)} tasks -> {project_queries} extra queries")
    print(f"  Distinct projects: {projects}")

    async with new_session() as session:
        tasks = await load_tasks(session)
        projects = len({task.project_id for task in tasks})
        assignees = len({task.assignee_id for task in tasks if task.assignee_id})

        with counter.record():
            await session.run_sync(read_project_and_assignee, tasks)

    both_queries = counter.count

    print(f"  Reading project + assignee -> {both_queries} extra queries")
    print(f"  Distinct projects: {projects}")
    print(f"  Distinct assignees: {assignees}")

    counter.print_sql()

    return project_queries, both_queries


async def check_3() -> int:
    heading("CHECK 3 — selectinload()")

    async with new_session() as session:
        with counter.record():
            tasks = (
                await session.scalars(
                    select(Task)
                    .options(
                        selectinload(Task.project),
                        selectinload(Task.assignee),
                    )
                    .order_by(Task.id.desc())
                    .limit(PAGE_SIZE)
                )
            ).all()

            await session.run_sync(read_project_and_assignee, tasks)

    print(f"  {len(tasks)} tasks + relationships -> {counter.count} SQL statements")

    counter.print_sql()

    return counter.count


async def main() -> None:
    print(f"Database: {settings.database_url}")
    print(f"Page size: {PAGE_SIZE}")

    endpoint_small, endpoint_large = await check_1()
    project_queries, both_queries = await check_2()
    eager = await check_3()

    heading("SUMMARY")

    print("  Real endpoint:")
    print(f"    10 tasks       -> {endpoint_small} statements")
    print(f"    {PAGE_SIZE} tasks      -> {endpoint_large} statements")
    print(f"    N+1?           -> {'NO' if endpoint_small == endpoint_large else 'YES'}")

    print("\n  Forced lazy loading:")
    print(f"    project        -> {project_queries} statements")
    print(f"    project + user -> {both_queries} statements")

    print("\n  Eager loading:")
    print(f"    selectinload() -> {eager} statements")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
