import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture()
async def db_session() -> AsyncSession:
    """Fixture that provides a clean database session for each test"""
    base_url, _, db_name = str(settings.database_url).rpartition("/")
    test_db_url = f"{base_url}/{db_name}_test"

    # Create a dedicated engine and sessionmaker for this test
    engine = create_async_engine(test_db_url)
    TestingSessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Setup: Drop and recreate all tables for a clean slate
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    try:
        async with TestingSessionLocal() as session:
            yield session
    finally:
        # Teardown: Clean up tables and close the connection pool
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture()
async def client(db_session: AsyncSession) -> AsyncClient:
    """Fixture that provides an AsyncClient with overridden database dependency"""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()

