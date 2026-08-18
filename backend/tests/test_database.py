"""Tests for database foundation, Base model, and session lifecycle."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db import session as db_session_module
from app.db.base import Base
from app.db.session import dispose_engine, get_db, get_engine


class DummyModel(Base):
    """Temporary model for testing declarative metadata mapping."""

    __tablename__ = "test_dummy_table"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)


class TestDatabaseFoundation:
    """Test suite for database initialization and session management."""

    def test_base_metadata(self) -> None:
        """Base metadata should register mapped models."""
        assert "test_dummy_table" in Base.metadata.tables
        table = Base.metadata.tables["test_dummy_table"]
        assert "id" in table.columns
        assert "name" in table.columns

    def test_get_engine_singleton(self) -> None:
        """get_engine should return an AsyncEngine instance."""
        engine = get_engine()
        assert isinstance(engine, AsyncEngine)
        assert get_engine() is engine

    @pytest.mark.asyncio
    async def test_dispose_engine(self) -> None:
        """dispose_engine should clean up the engine singleton."""
        _ = get_engine()
        await dispose_engine()
        assert db_session_module._engine is None

    @pytest.mark.asyncio
    async def test_get_db_session_lifecycle(self) -> None:
        """get_db should yield an AsyncSession and handle lifecycle."""
        # Use an in-memory sqlite async engine for testing session operations
        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        test_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

        original_factory = db_session_module._session_factory
        db_session_module._session_factory = test_factory

        try:
            # Test success path
            db_gen = get_db()
            session = await anext(db_gen)
            assert isinstance(session, AsyncSession)

            item = DummyModel(name="test_item")
            session.add(item)

            # Advance generator to completion (triggers commit)
            with pytest.raises(StopAsyncIteration):
                await anext(db_gen)

            # Verify item was committed
            async with test_factory() as verify_session:
                result = await verify_session.execute(select(DummyModel))
                items = result.scalars().all()
                assert len(items) == 1
                assert items[0].name == "test_item"

        finally:
            db_session_module._session_factory = original_factory
            await test_engine.dispose()

    @pytest.mark.asyncio
    async def test_get_db_rollback_on_error(self) -> None:
        """get_db should rollback when an exception occurs inside the context."""
        test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        test_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

        original_factory = db_session_module._session_factory
        db_session_module._session_factory = test_factory

        try:
            db_gen = get_db()
            session = await anext(db_gen)

            item = DummyModel(name="rollback_item")
            session.add(item)

            # Simulate an error raised by caller
            with pytest.raises(SQLAlchemyError):
                await db_gen.athrow(SQLAlchemyError("Simulated DB error"))

            # Verify item was not committed
            async with test_factory() as verify_session:
                result = await verify_session.execute(select(DummyModel))
                items = result.scalars().all()
                assert len(items) == 0

        finally:
            db_session_module._session_factory = original_factory
            await test_engine.dispose()
