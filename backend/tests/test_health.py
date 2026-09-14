"""Tests for GET /health and GET /health/ready endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine


class TestHealthEndpoint:
    """Test suite for the liveness health-check endpoint."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """GET /health should return HTTP 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_json(self, client: TestClient) -> None:
        """GET /health should return a JSON content-type."""
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_health_status_is_ok(self, client: TestClient) -> None:
        """GET /health response body should contain status='ok'."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_exact_payload(self, client: TestClient) -> None:
        """GET /health should return exact expected JSON payload."""
        response = client.get("/health")
        assert response.json() == {"status": "ok", "service": "codesage-api"}

    def test_health_service_name_present(self, client: TestClient) -> None:
        """GET /health response body should include a non-empty service name."""
        response = client.get("/health")
        data = response.json()
        assert data["service"] == "codesage-api"

    def test_health_response_schema(self, client: TestClient) -> None:
        """GET /health response body should match the HealthResponse schema."""
        response = client.get("/health")
        data = response.json()
        # Only the documented keys should be present.
        assert set(data.keys()) == {"status", "service"}

    def test_health_no_auth_required(self, client: TestClient) -> None:
        """GET /health should be accessible without any authentication headers."""
        response = client.get("/health")
        assert response.status_code != 401
        assert response.status_code != 403

    def test_health_carries_a_request_id_header(self, client: TestClient) -> None:
        """Every response should carry the RequestContextMiddleware's ID header."""
        response = client.get("/health")
        assert response.headers.get("X-Request-ID")

    def test_health_echoes_an_inbound_request_id(self, client: TestClient) -> None:
        """An inbound X-Request-ID should be preserved, not replaced."""
        response = client.get("/health", headers={"X-Request-ID": "caller-supplied-id"})
        assert response.headers["X-Request-ID"] == "caller-supplied-id"


class TestReadinessEndpoint:
    """Test suite for the database-aware readiness endpoint."""

    def test_readiness_returns_503_when_database_unreachable(
        self, client: TestClient
    ) -> None:
        """The test environment's DATABASE_URL is a placeholder that never
        actually connects, so /health/ready should honestly report that."""
        response = client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unreachable"

    def test_readiness_returns_200_when_database_reachable(
        self,
        client: TestClient,
        test_engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With a real, reachable engine, readiness should report ok/ok."""
        monkeypatch.setattr("app.api.v1.health.get_engine", lambda: test_engine)

        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "codesage-api",
            "database": "ok",
        }

    def test_readiness_no_auth_required(self, client: TestClient) -> None:
        """GET /health/ready should be accessible without authentication."""
        response = client.get("/health/ready")
        assert response.status_code != 401
        assert response.status_code != 403
