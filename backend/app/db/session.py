"""Async database engine and session factory.

Usage (as a FastAPI dependency)
--------------------------------
    from app.db.session import get_db
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.get("/example")
    async def example(db: AsyncSession = Depends(get_db)) -> ...:
        ...

The engine and session factory are created lazily on first access so
that importing this module (e.g. in tests that don't exercise the DB)
does not immediately attempt a database connection.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons — populated lazily via _get_engine()
# ---------------------------------------------------------------------------
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """Return the singleton async engine, creating it on first call.

    Raises
    ------
    RuntimeError
        If the database URL is missing or the engine cannot be constructed.
    """
    global _engine

    if _engine is not None:
        return _engine

    settings = get_settings()
    db_url = settings.async_database_url

    if not db_url:
        raise RuntimeError(
            "Database URL is not configured.  "
            "Set DATABASE_URL or the individual DB_* environment variables."
        )

    try:
        _engine = create_async_engine(
            db_url,
            echo=settings.DEBUG,  # log SQL in debug mode only
            pool_pre_ping=True,  # verify connections before use
            pool_size=10,
            max_overflow=20,
        )
        logger.info("Async database engine created (host=%s)", settings.DB_HOST)
        return _engine
    except Exception as exc:
        raise RuntimeError(f"Failed to create database engine: {exc}") from exc


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory, creating it on first call."""
    global _session_factory

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _session_factory


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def get_engine() -> AsyncEngine:
    """Return the application-level async engine (lazily initialised)."""
    return _get_engine()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` as a FastAPI dependency.

    The session is automatically committed on success and rolled back on
    error, then closed regardless of outcome.

    Raises
    ------
    SQLAlchemyError
        Re-raised after rollback so FastAPI's exception handlers can act.
    """
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Cleanly dispose of the engine pool.  Call during application shutdown."""
    global _engine

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database engine disposed.")
