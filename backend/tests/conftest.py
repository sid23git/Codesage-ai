"""Shared pytest fixtures with isolated in-memory test database."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Inject test settings BEFORE importing any application module
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_NAME", "codesage-api")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault(
    "SECRET_KEY",
    "test-secret-key-that-is-long-enough-for-validation-purposes-abc123",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService


@pytest_asyncio.fixture(name="test_engine")
async def fixture_test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an isolated in-memory SQLite database engine for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(name="db_session")
async def fixture_db_session(
    test_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session bound to the in-memory test database."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture(name="client")
def fixture_client(
    test_engine: AsyncEngine,
) -> Generator[TestClient, None, None]:
    """Return a TestClient wired to the isolated in-memory test database."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except SQLAlchemyError:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(name="test_user")
async def fixture_test_user(db_session: AsyncSession) -> User:
    """Create a default test user in the test database."""
    user_in = UserCreate(email="alice@example.com", password="password123")
    user = await AuthService.register_user(db_session, user_in)
    await db_session.commit()
    return user


@pytest_asyncio.fixture(name="other_user")
async def fixture_other_user(db_session: AsyncSession) -> User:
    """Create a second test user for authorization boundary tests."""
    user_in = UserCreate(email="bob@example.com", password="password123")
    user = await AuthService.register_user(db_session, user_in)
    await db_session.commit()
    return user


@pytest.fixture(name="auth_headers")
def fixture_auth_headers(test_user: User) -> dict[str, str]:
    """Generate authorization headers for test_user."""
    token = create_access_token(subject=test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(name="other_auth_headers")
def fixture_other_auth_headers(other_user: User) -> dict[str, str]:
    """Generate authorization headers for other_user."""
    token = create_access_token(subject=other_user.id)
    return {"Authorization": f"Bearer {token}"}
