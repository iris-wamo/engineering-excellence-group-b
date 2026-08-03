import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing the models package registers every table on Base.metadata,
# which is what --autogenerate compares the database against.
import app.models  # noqa: F401
from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config

# Take the database URL from our settings (.env) instead of alembic.ini.
# str() because database_url is a pydantic PostgresDsn, and set_main_option
# only accepts a plain string.
config.set_main_option("sqlalchemy.url", str(settings.database_url))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL to a file instead of running it ("alembic upgrade head --sql")."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    """Run alembic's sync migrations on the provided connection"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Also notice column type changes, not just added/removed columns.
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async DB connection, then hand it to alembic"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations with an async database connection"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
