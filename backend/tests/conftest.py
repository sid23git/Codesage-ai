"""Shared pytest fixtures.

The test suite overrides the application settings via environment variables
so no real database is required to run the health-check tests.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Inject minimal test settings BEFORE any app module is imported so that
# pydantic-settings picks them up from the environment.
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_NAME", "codesage-api")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault(
    "SECRET_KEY",
    "test-secret-key-that-is-long-enough-for-validation-purposes-abc123",
)
# Provide a syntactically valid DATABASE_URL so Settings initialises
# without raising a validation error.  The engine will not actually
# connect during health-check tests.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Return a ``TestClient`` wrapping the FastAPI application.

    The lifespan is **not** run by default so no real DB connection
    is attempted.  Individual tests that need the full lifespan can
    use ``with TestClient(app) as c:`` directly.
    """
    # Import app here (after env vars are set) to avoid premature
    # settings validation at module level.
    from app.main import app

    # ``raise_server_exceptions=True`` ensures test failures are not
    # silently swallowed.
    return TestClient(app, raise_server_exceptions=True)
