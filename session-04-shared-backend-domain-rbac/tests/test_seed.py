"""Tests for the database seeding script."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectUser, Task, User
from scripts.seed_data import seed_data
from tests.conftest import TEST_DATABASE_URL


@pytest.mark.asyncio
async def test_seed_data_script(db_session: AsyncSession) -> None:
    """Test that seed_data creates the expected number of records."""
    # Run seed script logic for small dataset targeting test database
    await seed_data(
        num_users=5,
        num_projects=2,
        num_tasks=25,
        batch_size=10,
        reset=True,
        db_url=TEST_DATABASE_URL,
    )

    # Verify counts in DB
    user_count = (await db_session.execute(select(func.count(User.id)))).scalar_one()
    proj_count = (await db_session.execute(select(func.count(Project.id)))).scalar_one()
    pu_count = (await db_session.execute(select(func.count(ProjectUser.user_id)))).scalar_one()
    task_count = (await db_session.execute(select(func.count(Task.id)))).scalar_one()

    assert user_count == 5
    assert proj_count == 2
    assert pu_count >= 2  # At least 1 owner per project
    assert task_count == 25
