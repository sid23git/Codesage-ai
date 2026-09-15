"""Alembic environment configuration.

This file is executed by Alembic before generating or applying migrations.
It reads the database URL from application settings (never from alembic.ini)
and configures both online (async) and offline migration modes.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import Base so Alembic's autogenerate can discover all mapped tables --
# and, critically, actually import the model modules too (via
# `app.models`, whose own __init__ already imports and re-exports every
# one, for exactly this purpose -- see that file's docstring). Importing
# Base alone does NOT populate Base.metadata; each model class's own
# import is what registers its table as a side effect of class
# definition.
#
# `alembic upgrade`/`downgrade` never consult target_metadata (they just
# replay each migration's own hardcoded op.* calls), so this omission was
# invisible for every command actually run against this project until
# `alembic check`/`--autogenerate` were first run standalone (not via
# pytest, which happens to import the models transitively through
# app.main first) -- see M8 Phase 2's CI verification, which is what
# caught it.
import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

# ---------------------------------------------------------------------------
# Alembic Config & logging
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with the value from application settings so that
# no credentials ever live in alembic.ini.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.async_database_url)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migrations (generate SQL script without connecting to DB)
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates a SQL script that can be reviewed and applied manually.
    No database connection is required.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (connect to DB and apply directly)
# ---------------------------------------------------------------------------
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within a connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using the async engine."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
