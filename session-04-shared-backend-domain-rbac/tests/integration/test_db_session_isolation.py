from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.project import Project
from app.models.workspace import Workspace
from app.schemas.project import ProjectCreate
from app.services.project_service import ProjectService
from tests.fixtures.database import rolled_back_session


async def _committed_count(database_url: str, model: type[Workspace | Project], slug: str) -> int:
    """How many rows with this slug are visible from outside the test session."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            query = select(func.count()).select_from(model).where(model.slug == slug)
            return int((await connection.execute(query)).scalar_one())
    finally:
        await engine.dispose()


def _unique_slug() -> str:
    return f"isolation-{uuid4().hex[:12]}"


async def test_commit_by_code_under_test_is_rolled_back_on_exit(test_database: str) -> None:
    slug = _unique_slug()

    async with rolled_back_session(test_database) as session:
        session.add(Workspace(name="Committed", slug=slug))
        await session.commit()
        # The commit worked for the session itself, but never reached the database.
        assert await session.scalar(select(Workspace).where(Workspace.slug == slug)) is not None
        assert await _committed_count(test_database, Workspace, slug) == 0

    assert await _committed_count(test_database, Workspace, slug) == 0


async def test_service_that_commits_leaves_nothing_behind(test_database: str) -> None:
    name = f"Isolation {uuid4().hex[:12]}"

    async with rolled_back_session(test_database) as session:
        project = await ProjectService.create_project(session, ProjectCreate(name=name))
        slug = project.slug

    assert await _committed_count(test_database, Project, slug) == 0


async def test_exception_inside_session_still_rolls_back(test_database: str) -> None:
    slug = _unique_slug()

    with pytest.raises(RuntimeError, match="boom"):
        async with rolled_back_session(test_database) as session:
            session.add(Workspace(name="Doomed", slug=slug))
            await session.commit()
            raise RuntimeError("boom")

    assert await _committed_count(test_database, Workspace, slug) == 0


async def test_rollback_by_code_under_test_keeps_earlier_commits(test_database: str) -> None:
    """A rollback() in application code undoes only its own work, not the test's setup.

    This is what lets DataFactory commit setup rows that survive a service rolling back.
    """
    setup_slug, failed_slug = _unique_slug(), _unique_slug()

    async with rolled_back_session(test_database) as session:
        session.add(Workspace(name="Setup", slug=setup_slug))
        await session.commit()

        session.add(Workspace(name="Failed write", slug=failed_slug))
        await session.flush()
        await session.rollback()

        assert await session.scalar(select(Workspace).where(Workspace.slug == setup_slug))
        assert await session.scalar(select(Workspace).where(Workspace.slug == failed_slug)) is None

    assert await _committed_count(test_database, Workspace, setup_slug) == 0
