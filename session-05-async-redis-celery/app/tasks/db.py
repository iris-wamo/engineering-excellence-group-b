"""Worker database session management (run_async lives in taskflow_shared.concurrency)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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
