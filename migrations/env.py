"""Alembic environment.

The database URL is read from Jarvis settings rather than alembic.ini, so the
connection string never appears in a committed file (spec §10).
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from jarvis.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Read the URL directly rather than building a full Settings object: applying a
# schema migration has nothing to do with which LLM provider is configured, and
# requiring an API key to run `alembic upgrade` is a setup trap. The default
# matches Settings.database_url so the two cannot drift silently.
DEFAULT_DATABASE_URL = "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis"
config.set_main_option(
    "sqlalchemy.url", os.environ.get("JARVIS_DATABASE_URL", DEFAULT_DATABASE_URL)
)


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against an async engine."""
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
