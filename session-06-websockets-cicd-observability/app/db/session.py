"""Async database engine/session setup and the get_db FastAPI dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    global _sessionmaker
    if _sessionmaker is None:
        # Called through the module so the tracing instrumentation's wrapper applies
        engine = sqlalchemy_asyncio.create_async_engine(str(settings.database_url))
        _sessionmaker = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    async with _sessionmaker() as db:
        yield db
