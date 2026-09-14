"""Tests for per-IP rate limiting on auth and AI/ingestion endpoints.

The rest of the suite runs with RATE_LIMIT_ENABLED=false (set in
conftest.py) so hundreds of unrelated tests sharing one TestClient host
(slowapi's key_func resolves every TestClient request to the same
"testclient" address) aren't affected by shared in-memory counters. This
module flips the shared limiter on explicitly, only for its own tests, and
resets its counters before/after so tests here don't bleed into each other
or leak into the rest of the suite.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_github_client
from app.core.config import Settings
from app.core.rate_limit import limiter
from app.github.client import GitHubClient
from app.main import app


@pytest.fixture(autouse=True)
def _enable_rate_limiting() -> Iterator[None]:
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


def _settings_with(**overrides: object) -> Settings:
    return Settings(
        SECRET_KEY="a" * 32,
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        **overrides,  # type: ignore[arg-type]
    )


class TestAuthRateLimiting:
    """POST /auth/login and /auth/register are limited per client IP."""

    def test_login_returns_429_once_the_limit_is_exceeded(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.api.v1.auth.get_settings",
            lambda: _settings_with(RATE_LIMIT_AUTH="2/minute"),
        )
        payload = {"email": "nobody@example.com", "password": "wrong-password"}

        for _ in range(2):
            response = client.post("/auth/login", json=payload)
            # Under the limit: a normal (failed) login, not a rate-limit block.
            assert response.status_code == 401

        blocked = client.post("/auth/login", json=payload)
        assert blocked.status_code == 429
        assert "rate limit" in blocked.json()["detail"].lower()

    def test_register_returns_429_once_the_limit_is_exceeded(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.api.v1.auth.get_settings",
            lambda: _settings_with(RATE_LIMIT_AUTH="2/minute"),
        )

        for i in range(2):
            response = client.post(
                "/auth/register",
                json={"email": f"user{i}@example.com", "password": "securepass123"},
            )
            assert response.status_code == 201

        blocked = client.post(
            "/auth/register",
            json={"email": "user-blocked@example.com", "password": "securepass123"},
        )
        assert blocked.status_code == 429

    def test_rate_limit_response_has_the_standard_error_shape(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 429 body should look like every other error response
        (`{"detail": str}`), not slowapi's own default `{"error": str}`
        shape -- so the frontend's existing typed-error handling parses it
        with no special-casing."""
        monkeypatch.setattr(
            "app.api.v1.auth.get_settings",
            lambda: _settings_with(RATE_LIMIT_AUTH="1/minute"),
        )
        payload = {"email": "nobody@example.com", "password": "wrong"}
        client.post("/auth/login", json=payload)

        blocked = client.post("/auth/login", json=payload)
        assert blocked.status_code == 429
        body = blocked.json()
        assert set(body.keys()) == {"detail"}
        assert isinstance(body["detail"], str)


class TestIngestRateLimiting:
    """POST /repositories/{id}/ingest is limited per client IP."""

    def test_ingest_returns_429_once_the_limit_is_exceeded(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "app.api.v1.repositories.get_settings",
            lambda: _settings_with(RATE_LIMIT_INGEST="1/minute"),
        )

        create_resp = client.post(
            "/repositories",
            json={
                "name": "Rate-Limited-Repo",
                "github_url": "https://github.com/octocat/Rate-Limited-Repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"print('hi')\n"
            info = tarfile.TarInfo(name="octocat-repo-abc1234/main.py")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.return_value = buf.getvalue()
        app.dependency_overrides[get_github_client] = lambda: mock_github
        try:
            first = client.post(f"/repositories/{repo_id}/ingest", headers=auth_headers)
            assert first.status_code == 200

            blocked = client.post(
                f"/repositories/{repo_id}/ingest", headers=auth_headers
            )
            assert blocked.status_code == 429
        finally:
            app.dependency_overrides.pop(get_github_client, None)


class TestRateLimitingDefaults:
    """The Settings *field* defaults to enabled (safe for a real
    deployment); it's only conftest.py's process-wide env override that
    turns it off for the rest of this test suite (see that file's
    comment). Both facts are worth pinning down explicitly."""

    def test_field_default_is_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no RATE_LIMIT_ENABLED in the environment at all, a fresh
        Settings instance should default to enabled."""
        monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
        settings = Settings(
            _env_file=None,
            SECRET_KEY="a" * 32,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        )
        assert settings.RATE_LIMIT_ENABLED is True

    def test_test_suite_env_disables_it(self) -> None:
        """conftest.py sets this so the other ~400 tests in this suite,
        which share one TestClient host, aren't affected by shared
        in-memory rate-limit counters."""
        import os

        assert os.environ.get("RATE_LIMIT_ENABLED") == "false"
