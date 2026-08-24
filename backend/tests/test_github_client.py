"""Unit tests for GitHubClient (app/github/client.py).

All tests use httpx's built-in MockTransport so no real network calls are made.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.github.client import GitHubClient
from app.github.exceptions import (
    GitHubMalformedResponseError,
    GitHubRateLimitError,
    GitHubRepositoryNotFoundError,
    GitHubTimeoutError,
    GitHubUpstreamError,
)
from app.github.schemas import GitHubRepoData

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

SAMPLE_GITHUB_RESPONSE: dict[str, Any] = {
    "id": 1296269,
    "owner": {"login": "octocat", "id": 583231},
    "name": "Hello-World",
    "full_name": "octocat/Hello-World",
    "description": "My first repository on GitHub!",
    "default_branch": "main",
    "language": "Python",
    "stargazers_count": 2048,
    "forks_count": 512,
    "open_issues_count": 10,
    "updated_at": "2024-01-15T12:00:00Z",
}


def _make_response(
    status_code: int,
    body: dict[str, Any] | str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response for testing."""
    if isinstance(body, dict):
        content = json.dumps(body).encode()
        content_type = "application/json"
    elif isinstance(body, str):
        content = body.encode()
        content_type = "text/plain"
    else:
        content = b""
        content_type = "application/json"

    response_headers = {"content-type": content_type}
    if headers:
        response_headers.update(headers)

    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=response_headers,
        request=httpx.Request(
            "GET", "https://api.github.com/repos/octocat/Hello-World"
        ),
    )


# ---------------------------------------------------------------------------
# Helper: patch httpx.AsyncClient.get to return a fixed response
# ---------------------------------------------------------------------------


def _patch_client_get(response: httpx.Response) -> Any:
    """Return a context manager that patches AsyncClient.get."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=response)
    return patch("app.github.client.httpx.AsyncClient", return_value=mock_client)


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


class TestGitHubClientSuccess:
    """Tests for successful GitHub API responses."""

    @pytest.mark.asyncio
    async def test_get_repository_returns_github_repo_data(self) -> None:
        """A valid 200 response is parsed into GitHubRepoData."""
        response = _make_response(200, SAMPLE_GITHUB_RESPONSE)

        with _patch_client_get(response):
            client = GitHubClient()
            data = await client.get_repository("octocat", "Hello-World")

        assert isinstance(data, GitHubRepoData)
        assert data.github_id == 1296269
        assert data.owner_login == "octocat"
        assert data.name == "Hello-World"
        assert data.full_name == "octocat/Hello-World"
        assert data.description == "My first repository on GitHub!"
        assert data.default_branch == "main"
        assert data.language == "Python"
        assert data.stargazers_count == 2048
        assert data.forks_count == 512
        assert data.open_issues_count == 10

    @pytest.mark.asyncio
    async def test_get_repository_null_description(self) -> None:
        """Repository with null description is handled."""
        payload = {**SAMPLE_GITHUB_RESPONSE, "description": None}
        response = _make_response(200, payload)

        with _patch_client_get(response):
            client = GitHubClient()
            data = await client.get_repository("octocat", "Hello-World")

        assert data.description is None

    @pytest.mark.asyncio
    async def test_get_repository_null_language(self) -> None:
        """Repository with null language is handled."""
        payload = {**SAMPLE_GITHUB_RESPONSE, "language": None}
        response = _make_response(200, payload)

        with _patch_client_get(response):
            client = GitHubClient()
            data = await client.get_repository("octocat", "Hello-World")

        assert data.language is None

    @pytest.mark.asyncio
    async def test_token_not_required(self) -> None:
        """Client works without a token (unauthenticated)."""
        response = _make_response(200, SAMPLE_GITHUB_RESPONSE)

        with _patch_client_get(response):
            client = GitHubClient(token=None)
            data = await client.get_repository("octocat", "Hello-World")

        assert data.github_id == 1296269


# ---------------------------------------------------------------------------
# Error translation cases
# ---------------------------------------------------------------------------


class TestGitHubClientErrors:
    """Tests that HTTP errors are translated to typed application exceptions."""

    @pytest.mark.asyncio
    async def test_404_raises_repository_not_found(self) -> None:
        """HTTP 404 → GitHubRepositoryNotFoundError."""
        response = _make_response(404, {"message": "Not Found"})

        with _patch_client_get(response):
            client = GitHubClient()
            with pytest.raises(GitHubRepositoryNotFoundError):
                await client.get_repository("owner", "nonexistent")

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(self) -> None:
        """HTTP 429 → GitHubRateLimitError."""
        response = _make_response(
            429,
            {"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0"},
        )

        with _patch_client_get(response):
            client = GitHubClient()
            with pytest.raises(GitHubRateLimitError):
                await client.get_repository("owner", "repo")

    @pytest.mark.asyncio
    async def test_403_with_rate_limit_header_raises_rate_limit_error(self) -> None:
        """HTTP 403 with x-ratelimit-remaining: 0 → GitHubRateLimitError."""
        response = _make_response(
            403,
            {"message": "Forbidden"},
            headers={"x-ratelimit-remaining": "0"},
        )

        with _patch_client_get(response):
            client = GitHubClient()
            with pytest.raises(GitHubRateLimitError):
                await client.get_repository("owner", "repo")

    @pytest.mark.asyncio
    async def test_500_raises_upstream_error(self) -> None:
        """HTTP 500 → GitHubUpstreamError."""
        response = _make_response(500, {"message": "Internal Server Error"})

        with _patch_client_get(response):
            client = GitHubClient()
            with pytest.raises(GitHubUpstreamError):
                await client.get_repository("owner", "repo")

    @pytest.mark.asyncio
    async def test_503_raises_upstream_error(self) -> None:
        """HTTP 503 → GitHubUpstreamError."""
        response = _make_response(503, {"message": "Service Unavailable"})

        with _patch_client_get(response):
            client = GitHubClient()
            with pytest.raises(GitHubUpstreamError):
                await client.get_repository("owner", "repo")

    @pytest.mark.asyncio
    async def test_timeout_raises_github_timeout_error(self) -> None:
        """httpx.TimeoutException → GitHubTimeoutError."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("app.github.client.httpx.AsyncClient", return_value=mock_client):
            client = GitHubClient(timeout=5.0)
            with pytest.raises(GitHubTimeoutError):
                await client.get_repository("owner", "repo")

    @pytest.mark.asyncio
    async def test_request_error_raises_upstream_error(self) -> None:
        """httpx.RequestError (network failure) → GitHubUpstreamError."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("connection refused")
        )

        with patch("app.github.client.httpx.AsyncClient", return_value=mock_client):
            client = GitHubClient()
            with pytest.raises(GitHubUpstreamError):
                await client.get_repository("owner", "repo")

    @pytest.mark.asyncio
    async def test_malformed_json_raises_malformed_response_error(self) -> None:
        """Non-JSON response body → GitHubMalformedResponseError."""
        response = _make_response(200, "this is not json")

        with _patch_client_get(response):
            client = GitHubClient()
            with pytest.raises(GitHubMalformedResponseError):
                await client.get_repository("owner", "repo")

    @pytest.mark.asyncio
    async def test_valid_json_missing_required_fields_raises_malformed(self) -> None:
        """JSON missing required fields → GitHubMalformedResponseError."""
        response = _make_response(200, {"id": 123})  # missing name, full_name, etc.

        with _patch_client_get(response):
            client = GitHubClient()
            with pytest.raises(GitHubMalformedResponseError):
                await client.get_repository("owner", "repo")
