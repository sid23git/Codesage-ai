"""Shared pytest fixtures with isolated in-memory test database.

Fast path (default): every test runs against an in-memory SQLite engine.
This is what makes the ~420-test suite runnable in a few minutes with zero
external services, and it's what CI/local `pytest` should keep using.

Postgres path (opt-in via TEST_DATABASE_URL): SQLite cannot exercise the
Postgres-only code paths in RAGService's retrievers -- VectorRetriever's
real `<=>` pgvector operator, or KeywordRetriever's real `tsv_content
@@ plainto_tsquery(...)` full-text search -- both fall back to a
documented, separate SQLite approximation instead (see
app/rag/retrieval/vector.py and keyword.py). Setting TEST_DATABASE_URL to
a real Postgres+pgvector DSN (e.g. the docker-compose `db` service) makes
`test_engine` run the actual Alembic migrations against it instead of
`Base.metadata.create_all` -- necessary because the tsvector generated
column and the HNSW/GIN indexes are created by migration 0004's raw SQL,
not by the SQLAlchemy model, so create_all alone can't reproduce them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

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
# Rate limiting is off by default across the suite: hundreds of tests share
# one TestClient host, and slowapi's per-IP counters would otherwise start
# rejecting requests partway through a single test file. It has its own
# dedicated coverage (test_rate_limiting.py), which flips it on explicitly.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _run_alembic(command: str, database_url: str) -> None:
    """Run one Alembic command as a subprocess against *database_url*.

    A subprocess (not the `alembic.command` API in-process) because
    alembic/env.py resolves its DSN from `get_settings()`, which is
    already cached (`@lru_cache`) by the time any test imports
    `app.main` -- overriding just this one subprocess's DATABASE_URL env
    var is simpler and more reliable than fighting that cache from
    inside the test process.
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", *command.split()],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest_asyncio.fixture(name="test_engine")
async def fixture_test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Yield a database engine for tests.

    Default: an isolated in-memory SQLite engine, schema created directly
    from the SQLAlchemy models (`Base.metadata.create_all`) -- fast, no
    external service required.

    If TEST_DATABASE_URL is set (a real Postgres+pgvector DSN): the real
    Alembic migrations are applied to it instead, so the schema includes
    the pgvector HNSW index and the generated `tsv_content` column + GIN
    index that only migration 0004's raw SQL creates -- `create_all`
    alone cannot reproduce those, and tests that exercise
    VectorRetriever/KeywordRetriever's real Postgres code paths need them
    to actually be there. Rolled back (`alembic downgrade base`) after
    each test for the same full isolation the SQLite path already has.
    """
    test_db_url = os.environ.get("TEST_DATABASE_URL")

    if test_db_url:
        _run_alembic("upgrade head", test_db_url)
        engine = create_async_engine(test_db_url, echo=False)

        yield engine

        await engine.dispose()
        _run_alembic("downgrade base", test_db_url)
        return

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
