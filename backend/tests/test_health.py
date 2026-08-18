"""Tests for GET /health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


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
