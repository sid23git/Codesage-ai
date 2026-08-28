"""API integration and authorization tests for repository ingestion endpoints."""

from __future__ import annotations

import io
import tarfile
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import get_github_client
from app.github.client import GitHubClient
from app.github.exceptions import (
    GitHubArchiveSizeExceededError,
    GitHubRateLimitError,
    GitHubRepositoryNotFoundError,
    GitHubTimeoutError,
)
from app.main import app


def _create_mock_tarball() -> bytes:
    """Create in-memory tarball payload for API tests."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        files = {
            "octocat-api-test-c8d7e6f/main.py": b"print('codesage api')\n",
            "octocat-api-test-c8d7e6f/README.md": b"# Test API\n",
        }
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestIngestEndpointSuccess:
    """Verify successful ingestion triggering via REST API."""

    def test_owner_trigger_ingest_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        # Create a repo
        create_resp = client.post(
            "/repositories",
            json={
                "name": "Api-Test-Repo",
                "github_url": "https://github.com/octocat/Api-Test-Repo",
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        repo_id = create_resp.json()["id"]

        # Mock GitHubClient
        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.return_value = _create_mock_tarball()
        app.dependency_overrides[get_github_client] = lambda: mock_github

        # Trigger ingestion
        resp = client.post(f"/repositories/{repo_id}/ingest", headers=auth_headers)
        assert resp.status_code == 200

        data = resp.json()
        assert data["repository_id"] == repo_id
        assert data["status"] == "completed"
        assert data["commit_sha"] == "c8d7e6f"
        assert data["file_count"] == 2
        assert data["primary_language"] == "Python"
        assert "language_stats" in data
        assert "file_catalog" in data
        assert len(data["file_catalog"]) == 2

        # Clean override
        app.dependency_overrides.pop(get_github_client, None)


class TestIngestEndpointAuthorization:
    """Verify authentication and user isolation boundaries."""

    def test_unauthenticated_ingest_returns_401(self, client: TestClient) -> None:
        resp = client.post("/repositories/1/ingest")
        assert resp.status_code == 401

    def test_other_user_cannot_ingest_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        # Alice creates a repo
        create_resp = client.post(
            "/repositories",
            json={
                "name": "Alice-Repo",
                "github_url": "https://github.com/alice/Alice-Repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        # Bob attempts to ingest Alice's repo
        resp = client.post(
            f"/repositories/{repo_id}/ingest", headers=other_auth_headers
        )
        assert resp.status_code == 404

    def test_ingest_nonexistent_repo_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        resp = client.post("/repositories/99999/ingest", headers=auth_headers)
        assert resp.status_code == 404


class TestIngestEndpointErrors:
    """Verify mapping of errors to appropriate HTTP status codes."""

    def test_github_404_maps_to_http_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        create_resp = client.post(
            "/repositories",
            json={
                "name": "Missing-Repo",
                "github_url": "https://github.com/octocat/Missing-Repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.side_effect = GitHubRepositoryNotFoundError(
            "Not Found"
        )
        app.dependency_overrides[get_github_client] = lambda: mock_github

        resp = client.post(f"/repositories/{repo_id}/ingest", headers=auth_headers)
        assert resp.status_code == 404
        app.dependency_overrides.pop(get_github_client, None)

    def test_github_rate_limit_maps_to_http_429(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        create_resp = client.post(
            "/repositories",
            json={
                "name": "Rate-Repo",
                "github_url": "https://github.com/octocat/Rate-Repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.side_effect = GitHubRateLimitError(
            "Rate limit exceeded"
        )
        app.dependency_overrides[get_github_client] = lambda: mock_github

        resp = client.post(f"/repositories/{repo_id}/ingest", headers=auth_headers)
        assert resp.status_code == 429
        app.dependency_overrides.pop(get_github_client, None)

    def test_github_timeout_maps_to_http_504(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        create_resp = client.post(
            "/repositories",
            json={
                "name": "Timeout-Repo",
                "github_url": "https://github.com/octocat/Timeout-Repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.side_effect = GitHubTimeoutError("Timed out")
        app.dependency_overrides[get_github_client] = lambda: mock_github

        resp = client.post(f"/repositories/{repo_id}/ingest", headers=auth_headers)
        assert resp.status_code == 504
        app.dependency_overrides.pop(get_github_client, None)

    def test_archive_size_exceeded_maps_to_http_413(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        create_resp = client.post(
            "/repositories",
            json={
                "name": "Big-Repo",
                "github_url": "https://github.com/octocat/Big-Repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.side_effect = GitHubArchiveSizeExceededError(
            "Archive too large"
        )
        app.dependency_overrides[get_github_client] = lambda: mock_github

        resp = client.post(f"/repositories/{repo_id}/ingest", headers=auth_headers)
        assert resp.status_code == 413
        app.dependency_overrides.pop(get_github_client, None)


class TestIngestionQueryEndpoints:
    """Verify GET endpoints for inspecting ingestion state."""

    def test_get_latest_ingestion_and_list_flow(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        create_resp = client.post(
            "/repositories",
            json={
                "name": "Query-Test-Repo",
                "github_url": "https://github.com/octocat/Query-Test-Repo",
            },
            headers=auth_headers,
        )
        repo_id = create_resp.json()["id"]

        # Before ingestion: GET /ingestion returns 404
        resp = client.get(f"/repositories/{repo_id}/ingestion", headers=auth_headers)
        assert resp.status_code == 404

        # Perform ingestion
        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.return_value = _create_mock_tarball()
        app.dependency_overrides[get_github_client] = lambda: mock_github

        ingest_resp = client.post(
            f"/repositories/{repo_id}/ingest", headers=auth_headers
        )
        assert ingest_resp.status_code == 200
        ingestion_id = ingest_resp.json()["id"]
        app.dependency_overrides.pop(get_github_client, None)

        # GET /ingestion returns latest
        latest_resp = client.get(
            f"/repositories/{repo_id}/ingestion", headers=auth_headers
        )
        assert latest_resp.status_code == 200
        assert latest_resp.json()["id"] == ingestion_id

        # GET /ingestions returns list
        list_resp = client.get(
            f"/repositories/{repo_id}/ingestions", headers=auth_headers
        )
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        # GET /ingestions/{id} returns single
        single_resp = client.get(
            f"/repositories/{repo_id}/ingestions/{ingestion_id}", headers=auth_headers
        )
        assert single_resp.status_code == 200
        assert single_resp.json()["id"] == ingestion_id

        # Other user cannot access
        other_resp = client.get(
            f"/repositories/{repo_id}/ingestion", headers=other_auth_headers
        )
        assert other_resp.status_code == 404

        other_list_resp = client.get(
            f"/repositories/{repo_id}/ingestions", headers=other_auth_headers
        )
        assert other_list_resp.status_code == 404
