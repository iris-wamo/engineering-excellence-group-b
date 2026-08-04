from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    global _sessionmaker
    if _sessionmaker is None:
        engine = create_async_engine(str(settings.database_url))
        _sessionmaker = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    async with _sessionmaker() as db:
        yield db
