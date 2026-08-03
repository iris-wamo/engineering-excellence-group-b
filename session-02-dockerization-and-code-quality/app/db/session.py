from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# str() because database_url is a pydantic PostgresDsn; create_engine wants a plain string.
engine = create_async_engine(str(settings.database_url))
AsyncSessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        yield db
