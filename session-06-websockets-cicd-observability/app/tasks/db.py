"""Worker database session management (run_async lives in taskflow_shared.concurrency)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings


@asynccontextmanager
async def get_worker_db() -> AsyncGenerator[AsyncSession, None]:
    """Isolated async database session context manager for Celery workers.

    Uses NullPool and explicitly disposes the engine upon exit to ensure connections
    are not reused across event loops or worker processes.
    """
    # Called through the module so the tracing instrumentation's wrapper applies
    engine = sqlalchemy_asyncio.create_async_engine(str(settings.database_url), poolclass=NullPool)
    sessionmaker = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    async with sessionmaker() as db:
        try:
            yield db
        finally:
            await engine.dispose()
