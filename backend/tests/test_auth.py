"""Tests for authentication, registration, and token validation."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.user import User


class TestRegistration:
    """Test suite for POST /auth/register."""

    def test_register_success(self, client: TestClient) -> None:
        """User registration with valid email and password should return 201."""
        response = client.post(
            "/auth/register",
            json={"email": "newuser@example.com", "password": "securepassword123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["is_active"] is True
        assert "id" in data
        assert "password" not in data
        assert "password_hash" not in data

    def test_register_duplicate_email_rejected(
        self, client: TestClient, test_user: User
    ) -> None:
        """Registering with an existing email should return 409 Conflict."""
        response = client.post(
            "/auth/register",
            json={"email": test_user.email, "password": "anotherpassword123"},
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    def test_register_invalid_email_format(self, client: TestClient) -> None:
        """Registering with malformed email should return 422 Unprocessable Entity."""
        response = client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "securepassword123"},
        )
        assert response.status_code == 422

    def test_register_short_password_rejected(self, client: TestClient) -> None:
        """Registering with password shorter than 8 characters should return 422."""
        response = client.post(
            "/auth/register",
            json={"email": "shortpw@example.com", "password": "short"},
        )
        assert response.status_code == 422

    def test_register_missing_fields_rejected(self, client: TestClient) -> None:
        """Registering without required fields should return 422."""
        response = client.post("/auth/register", json={})
        assert response.status_code == 422

    def test_register_rejected_when_registration_disabled(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /auth/register returns 403 when REGISTRATION_ENABLED is false."""
        from app.core.config import Settings

        disabled_settings = Settings(
            SECRET_KEY="a" * 32,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
            REGISTRATION_ENABLED=False,
        )
        monkeypatch.setattr("app.api.v1.auth.get_settings", lambda: disabled_settings)

        response = client.post(
            "/auth/register",
            json={"email": "blocked@example.com", "password": "securepassword123"},
        )
        assert response.status_code == 403


class TestLogin:
    """Test suite for POST /auth/login."""

    def test_login_success(self, client: TestClient, test_user: User) -> None:
        """Logging in with correct credentials should return 200 and access token."""
        response = client.post(
            "/auth/login",
            json={"email": test_user.email, "password": "password123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    def test_login_incorrect_password(
        self, client: TestClient, test_user: User
    ) -> None:
        """Logging in with wrong password should return 401."""
        response = client.post(
            "/auth/login",
            json={"email": test_user.email, "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"

    def test_login_unknown_user(self, client: TestClient) -> None:
        """Logging in with non-existent email should return 401 generic error."""
        response = client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "password123"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"


class TestAuthenticationProtection:
    """Test suite for GET /auth/me and protected access."""

    def test_get_me_authenticated(
        self, client: TestClient, test_user: User, auth_headers: dict[str, str]
    ) -> None:
        """GET /auth/me with valid Bearer token should return user profile."""
        response = client.get("/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id
        assert data["email"] == test_user.email
        assert data["is_active"] is True
        assert "password" not in data
        assert "password_hash" not in data

    def test_get_me_missing_token_rejected(self, client: TestClient) -> None:
        """GET /auth/me without authorization header should return 401."""
        response = client.get("/auth/me")
        assert response.status_code == 401

    def test_get_me_invalid_token_rejected(self, client: TestClient) -> None:
        """GET /auth/me with garbage token should return 401."""
        response = client.get(
            "/auth/me", headers={"Authorization": "Bearer invalid.token.payload"}
        )
        assert response.status_code == 401

    def test_get_me_expired_token_rejected(
        self, client: TestClient, test_user: User
    ) -> None:
        """GET /auth/me with expired token should return 401."""
        expired_token = create_access_token(
            subject=test_user.id,
            expires_delta=timedelta(seconds=-10),
        )
        response = client.get(
            "/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_me_inactive_user_rejected(
        self, client: TestClient, test_user: User, db_session: AsyncSession
    ) -> None:
        """GET /auth/me for inactive user should return 401."""
        test_user.is_active = False
        await db_session.commit()

        token = create_access_token(subject=test_user.id)
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "inactive" in response.json()["detail"].lower()
