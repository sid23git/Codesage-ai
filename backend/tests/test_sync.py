"""Integration tests for POST /repositories/{id}/sync.

The GitHub client is mocked via FastAPI's dependency_overrides so no real
network calls are made.  All other infrastructure (auth, database, ownership)
is exercised with the real in-memory SQLite test DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.deps import get_github_client
from app.github.exceptions import (
    GitHubMalformedResponseError,
    GitHubRateLimitError,
    GitHubRepositoryNotFoundError,
    GitHubTimeoutError,
    GitHubUpstreamError,
    InvalidGitHubURLError,
)
from app.github.schemas import GitHubRepoData
from app.main import app
from app.models.user import User

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_GITHUB_DATA = GitHubRepoData(
    id=1296269,
    owner="octocat",
    name="Hello-World",
    full_name="octocat/Hello-World",
    description="My first repository on GitHub!",
    default_branch="main",
    language="Python",
    stargazers_count=2048,
    forks_count=512,
    open_issues_count=10,
    updated_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
)

_REPO_PAYLOAD = {
    "name": "Hello-World",
    "github_url": "https://github.com/octocat/Hello-World",
    "description": "Original description",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_github_client(
    return_value: GitHubRepoData | None = None,
    side_effect: Any = None,
) -> MagicMock:
    """Build a mock GitHubClient whose get_repository is an AsyncMock."""
    mock = MagicMock()
    if side_effect is not None:
        mock.get_repository = AsyncMock(side_effect=side_effect)
    else:
        mock.get_repository = AsyncMock(return_value=return_value or _GITHUB_DATA)
    return mock


# ---------------------------------------------------------------------------
# Success scenarios
# ---------------------------------------------------------------------------


class TestSyncRepositorySuccess:
    """Happy-path sync tests."""

    def test_owner_sync_succeeds_returns_200(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Authenticated owner can sync their repository and receives 200."""
        # Create repository
        create_resp = client.post(
            "/repositories", json=_REPO_PAYLOAD, headers=auth_headers
        )
        assert create_resp.status_code == 201
        repo_id = create_resp.json()["id"]

        # Override GitHub client dependency
        app.dependency_overrides[get_github_client] = lambda: _mock_github_client()

        try:
            sync_resp = client.post(
                f"/repositories/{repo_id}/sync", headers=auth_headers
            )
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert sync_resp.status_code == 200

    def test_sync_sets_status_to_ready(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """After a successful sync, status is set to 'ready'."""
        create_resp = client.post(
            "/repositories", json=_REPO_PAYLOAD, headers=auth_headers
        )
        repo_id = create_resp.json()["id"]
        assert create_resp.json()["status"] == "pending"

        app.dependency_overrides[get_github_client] = lambda: _mock_github_client()
        try:
            data = client.post(
                f"/repositories/{repo_id}/sync", headers=auth_headers
            ).json()
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert data["status"] == "ready"

    def test_sync_persists_github_metadata(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GitHub metadata fields are persisted and returned."""
        create_resp = client.post(
            "/repositories", json=_REPO_PAYLOAD, headers=auth_headers
        )
        repo_id = create_resp.json()["id"]

        app.dependency_overrides[get_github_client] = lambda: _mock_github_client()
        try:
            data = client.post(
                f"/repositories/{repo_id}/sync", headers=auth_headers
            ).json()
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert data["github_repository_id"] == 1296269
        assert data["github_owner"] == "octocat"
        assert data["default_branch"] == "main"
        assert data["stars"] == 2048
        assert data["forks"] == 512
        assert data["open_issues"] == 10
        assert data["primary_language"] == "Python"
        assert data["description"] == "My first repository on GitHub!"

    def test_sync_sets_last_synced_at(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """last_synced_at is populated after a successful sync."""
        create_resp = client.post(
            "/repositories", json=_REPO_PAYLOAD, headers=auth_headers
        )
        repo_id = create_resp.json()["id"]
        assert create_resp.json()["last_synced_at"] is None

        app.dependency_overrides[get_github_client] = lambda: _mock_github_client()
        try:
            data = client.post(
                f"/repositories/{repo_id}/sync", headers=auth_headers
            ).json()
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert data["last_synced_at"] is not None

    def test_sync_updates_full_name_from_github(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """full_name is updated to match the GitHub response."""
        create_resp = client.post(
            "/repositories", json=_REPO_PAYLOAD, headers=auth_headers
        )
        repo_id = create_resp.json()["id"]

        app.dependency_overrides[get_github_client] = lambda: _mock_github_client()
        try:
            data = client.post(
                f"/repositories/{repo_id}/sync", headers=auth_headers
            ).json()
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert data["full_name"] == "octocat/Hello-World"


# ---------------------------------------------------------------------------
# Authorization scenarios
# ---------------------------------------------------------------------------


class TestSyncRepositoryAuthorization:
    """Ownership and authentication boundary tests."""

    def test_unauthenticated_sync_returns_401(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Unauthenticated request to sync endpoint returns 401."""
        create_resp = client.post(
            "/repositories", json=_REPO_PAYLOAD, headers=auth_headers
        )
        repo_id = create_resp.json()["id"]

        sync_resp = client.post(f"/repositories/{repo_id}/sync")
        assert sync_resp.status_code == 401

    def test_other_user_cannot_sync_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        """User B cannot sync User A's repository — returns 404."""
        create_resp = client.post(
            "/repositories", json=_REPO_PAYLOAD, headers=auth_headers
        )
        repo_id = create_resp.json()["id"]

        app.dependency_overrides[get_github_client] = lambda: _mock_github_client()
        try:
            sync_resp = client.post(
                f"/repositories/{repo_id}/sync", headers=other_auth_headers
            )
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert sync_resp.status_code == 404

    def test_sync_nonexistent_repository_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Syncing a repository ID that doesn't exist returns 404."""
        app.dependency_overrides[get_github_client] = lambda: _mock_github_client()
        try:
            sync_resp = client.post("/repositories/99999/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert sync_resp.status_code == 404


# ---------------------------------------------------------------------------
# GitHub failure translation
# ---------------------------------------------------------------------------


class TestSyncRepositoryGitHubErrors:
    """Tests that GitHub integration errors produce correct HTTP status codes."""

    def _create_repo(self, client: TestClient, auth_headers: dict[str, str]) -> int:
        resp = client.post("/repositories", json=_REPO_PAYLOAD, headers=auth_headers)
        assert resp.status_code == 201
        return int(resp.json()["id"])

    def test_github_404_returns_http_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GitHub 404 → HTTP 404."""
        repo_id = self._create_repo(client, auth_headers)
        mock = _mock_github_client(
            side_effect=GitHubRepositoryNotFoundError("not found")
        )

        app.dependency_overrides[get_github_client] = lambda: mock
        try:
            resp = client.post(f"/repositories/{repo_id}/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert resp.status_code == 404

    def test_github_rate_limit_returns_http_429(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GitHub rate limit → HTTP 429."""
        repo_id = self._create_repo(client, auth_headers)
        mock = _mock_github_client(side_effect=GitHubRateLimitError("rate limited"))

        app.dependency_overrides[get_github_client] = lambda: mock
        try:
            resp = client.post(f"/repositories/{repo_id}/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert resp.status_code == 429

    def test_github_timeout_returns_http_504(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GitHub timeout → HTTP 504."""
        repo_id = self._create_repo(client, auth_headers)
        mock = _mock_github_client(side_effect=GitHubTimeoutError("timed out"))

        app.dependency_overrides[get_github_client] = lambda: mock
        try:
            resp = client.post(f"/repositories/{repo_id}/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert resp.status_code == 504

    def test_github_server_error_returns_http_502(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GitHub 5xx → HTTP 502."""
        repo_id = self._create_repo(client, auth_headers)
        mock = _mock_github_client(side_effect=GitHubUpstreamError("server error"))

        app.dependency_overrides[get_github_client] = lambda: mock
        try:
            resp = client.post(f"/repositories/{repo_id}/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert resp.status_code == 502

    def test_github_malformed_response_returns_http_502(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Malformed GitHub response → HTTP 502."""
        repo_id = self._create_repo(client, auth_headers)
        mock = _mock_github_client(side_effect=GitHubMalformedResponseError("bad JSON"))

        app.dependency_overrides[get_github_client] = lambda: mock
        try:
            resp = client.post(f"/repositories/{repo_id}/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert resp.status_code == 502

    def test_github_failure_sets_status_to_failed(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """After a GitHub failure, repository status is set to 'failed'."""
        repo_id = self._create_repo(client, auth_headers)
        mock = _mock_github_client(
            side_effect=GitHubRepositoryNotFoundError("not found")
        )

        app.dependency_overrides[get_github_client] = lambda: mock
        try:
            client.post(f"/repositories/{repo_id}/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        # Confirm status changed to failed
        get_resp = client.get(f"/repositories/{repo_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "failed"

    def test_invalid_github_url_returns_http_400(
        self, client: TestClient, auth_headers: dict[str, str], test_user: User
    ) -> None:
        """InvalidGitHubURLError raised by sync_repository → HTTP 400."""
        repo_id = self._create_repo(client, auth_headers)
        mock = _mock_github_client(side_effect=InvalidGitHubURLError("bad url"))

        app.dependency_overrides[get_github_client] = lambda: mock
        try:
            resp = client.post(f"/repositories/{repo_id}/sync", headers=auth_headers)
        finally:
            app.dependency_overrides.pop(get_github_client, None)

        assert resp.status_code == 400
