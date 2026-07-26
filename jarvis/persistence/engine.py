"""Async engine and session management.

Sessions are provided by dependency injection, never imported as a module-level
global, so tests and workflow activities can supply their own.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from jarvis.kernel.config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    """Create the async database engine.

    Args:
        settings: Root configuration.

    Returns:
        A configured `AsyncEngine`. ``echo`` is never enabled, because SQL echo
        would print bound parameters that may contain business data (spec §10).
    """
    return create_async_engine(
        settings.database_url.get_secret_value(),
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to ``engine``."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Yield a session inside a transaction, committing or rolling back.

    Args:
        factory: Session factory from `build_session_factory`.

    Yields:
        An open `AsyncSession`.
    """
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
