import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import PostgresDsn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_base_url, _, _db_name = str(settings.database_url).rpartition("/")
MIGRATIONS_DB_NAME = f"{_db_name}_migrations_test"
MIGRATIONS_URL = f"{_base_url}/{MIGRATIONS_DB_NAME}"
ADMIN_URL = f"{_base_url}/postgres"


async def _run_on_admin_database(*statements: str) -> None:
    engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def _scalar(sql: str, **params: Any) -> Any:
    engine = create_async_engine(MIGRATIONS_URL)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text(sql), params)
    finally:
        await engine.dispose()


def _table_exists(table: str) -> bool:
    return bool(
        asyncio.run(_scalar("SELECT to_regclass(:name) IS NOT NULL", name=f"public.{table}"))
    )


def _index_exists(index: str) -> bool:
    return bool(
        asyncio.run(
            _scalar("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)", name=index)
        )
    )


def _current_revision() -> Any:
    return asyncio.run(_scalar("SELECT version_num FROM alembic_version"))


@pytest.fixture(scope="module")
def migrations_config() -> Generator[Config, None, None]:
    asyncio.run(
        _run_on_admin_database(
            f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}" WITH (FORCE)',
            f'CREATE DATABASE "{MIGRATIONS_DB_NAME}"',
        )
    )
    original_database_url = settings.database_url
    settings.database_url = PostgresDsn(MIGRATIONS_URL)

    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    yield config

    settings.database_url = original_database_url
    asyncio.run(
        _run_on_admin_database(f'DROP DATABASE IF EXISTS "{MIGRATIONS_DB_NAME}" WITH (FORCE)')
    )


def test_upgrade_head_then_downgrade_one(migrations_config: Config) -> None:
    command.upgrade(migrations_config, "head")

    head = ScriptDirectory.from_config(migrations_config).get_current_head()
    assert _current_revision() == head
    assert _table_exists("task_comment")
    assert _index_exists("ix_task_comment_task_id")

    command.downgrade(migrations_config, "-1")

    assert _current_revision() != head
    assert not _table_exists("task_comment")
    assert not _index_exists("ix_task_comment_task_id")
    assert _table_exists("task")

    command.upgrade(migrations_config, "head")
    assert _table_exists("task_comment")


def test_the_comment_table_matches_the_model(migrations_config: Config) -> None:
    command.upgrade(migrations_config, "head")

    columns = asyncio.run(
        _scalar(
            "SELECT string_agg(column_name || ':' || data_type || ':' || is_nullable, ', ' "
            "ORDER BY ordinal_position) FROM information_schema.columns "
            "WHERE table_name = 'task_comment'"
        )
    )

    assert columns == (
        "id:integer:NO, task_id:integer:NO, user_id:integer:NO, content:text:NO, "
        "created_at:timestamp with time zone:NO, updated_at:timestamp with time zone:NO"
    )
