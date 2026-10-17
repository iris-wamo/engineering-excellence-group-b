"""Worker database session management and async execution utilities."""

import asyncio
import concurrent.futures
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings


@asynccontextmanager
async def get_worker_db() -> AsyncGenerator[AsyncSession, None]:
    """Isolated async database session context manager for Celery workers.

    Uses NullPool and explicitly disposes the engine upon exit to ensure connections
    are not reused across event loops or worker processes.
    """
    engine = create_async_engine(str(settings.database_url), poolclass=NullPool)
    sessionmaker = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    async with sessionmaker() as db:
        try:
            yield db
        finally:
            await engine.dispose()


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously.

    Safely handles cases where an event loop is already running in the current thread
    (such as during pytest-asyncio test runs) by running in a separate worker thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
