"""Tests for the database seeding script."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectUser, Task, User, Workspace, WorkspaceUser
from scripts.seed_data import seed_data
from tests.conftest import TEST_DATABASE_URL


@pytest.mark.asyncio
async def test_seed_data_script() -> None:
    """Test that seed_data creates the expected number of records including workspaces."""
    # Run seed script logic for small dataset targeting test database
    await seed_data(
        num_workspaces=2,
        num_users=5,
        num_projects=2,
        num_tasks=25,
        batch_size=10,
        reset=True,
        db_url=TEST_DATABASE_URL,
    )

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(TEST_DATABASE_URL)
    async with AsyncSession(engine) as session:
        ws_count = (await session.execute(select(func.count(Workspace.id)))).scalar_one()
        wu_count = (await session.execute(select(func.count(WorkspaceUser.user_id)))).scalar_one()
        user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
        proj_count = (await session.execute(select(func.count(Project.id)))).scalar_one()
        pu_count = (await session.execute(select(func.count(ProjectUser.user_id)))).scalar_one()
        task_count = (await session.execute(select(func.count(Task.id)))).scalar_one()

        assert ws_count == 2
        assert wu_count >= 5  # Each of 5 users has at least 1 workspace membership
        assert user_count == 5
        assert proj_count == 2
        assert pu_count >= 2  # At least 1 owner per project
        assert task_count == 25

        # Restore default workspace 1 for subsequent tests
        await session.execute(
            text(
                "INSERT INTO workspace (id, name, slug, description, created_at, updated_at) "
                "VALUES (1, 'Default Workspace', 'default-workspace', "
                "'System default workspace', NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING;"
            )
        )
        await session.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('workspace', 'id'), "
                "COALESCE((SELECT MAX(id) FROM workspace), 1));"
            )
        )
        await session.commit()
    await engine.dispose()
