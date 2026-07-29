import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app


def _test_database_url() -> str:
    """Same server/credentials as DATABASE_URL, but against a dedicated `<db>_test` database."""
    base_url, _, db_name = str(settings.database_url).rpartition("/")
    return f"{base_url}/{db_name}_test"


@pytest.fixture(scope="session")
def engine() -> Engine:
    return create_engine(_test_database_url())


@pytest.fixture()
def db_session(engine: Engine) -> Session:
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    def override_get_db() -> Session:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
