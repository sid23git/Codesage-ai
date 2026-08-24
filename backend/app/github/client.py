"""GitHub API client.

Provides a thin, testable abstraction over the GitHub REST API.  All outbound
HTTP logic lives here; no other module should import ``httpx`` directly for
GitHub requests.

Architecture
------------
::

    API Route
       ↓
    Repository Service
       ↓
    GitHubClient          ← this module
       ↓
    GitHub REST API

Usage
-----
::

    client = GitHubClient(token="ghp_...", timeout=10.0)
    data = await client.get_repository("octocat", "Hello-World")

Security
--------
- The Authorization header value is never logged.
- Only ``github.com`` should ever be called (callers are expected to use
  ``parse_github_url`` to validate the hostname before constructing owner/repo).
- Explicit timeout prevents indefinite hanging connections.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from app.github.exceptions import (
    GitHubMalformedResponseError,
    GitHubRateLimitError,
    GitHubRepositoryNotFoundError,
    GitHubTimeoutError,
    GitHubUpstreamError,
)
from app.github.schemas import GitHubRepoData

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_ACCEPT_HEADER = "application/vnd.github+json"
_API_VERSION_HEADER = "2022-11-28"


class GitHubClient:
    """Reusable, async-friendly GitHub API client.

    Parameters
    ----------
    token:
        Optional GitHub Personal Access Token.  When supplied, it is included
        in the ``Authorization`` header to raise the rate limit.  If ``None``,
        requests are made unauthenticated (60 req/h per IP).
    timeout:
        Timeout in seconds for each outbound request.  Defaults to 10 s.
    """

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._token = token
        self._timeout = timeout

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for a GitHub API request.

        The Authorization header value is intentionally not logged anywhere in
        this method or its callers.
        """
        headers: dict[str, str] = {
            "Accept": _ACCEPT_HEADER,
            "X-GitHub-Api-Version": _API_VERSION_HEADER,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def get_repository(self, owner: str, repo: str) -> GitHubRepoData:
        """Fetch public metadata for a GitHub repository.

        Parameters
        ----------
        owner:
            GitHub user or organisation login.
        repo:
            Repository name (without ``.git`` suffix).

        Returns
        -------
        GitHubRepoData
            Validated internal representation of the repository metadata.

        Raises
        ------
        GitHubRepositoryNotFoundError
            If GitHub returns 404.
        GitHubRateLimitError
            If GitHub returns 403 or 429 with an exhausted rate limit.
        GitHubUpstreamError
            If GitHub returns an unexpected 5xx response.
        GitHubTimeoutError
            If the request exceeds ``self._timeout`` seconds.
        GitHubMalformedResponseError
            If the response body cannot be parsed into ``GitHubRepoData``.
        """
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}"
        logger.debug("GitHub API request: GET %s", url)

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
            ) as client:
                response = await client.get(url, headers=self._build_headers())
        except httpx.TimeoutException as exc:
            logger.warning("GitHub API timeout for %s/%s: %s", owner, repo, exc)
            raise GitHubTimeoutError(
                f"Request to GitHub timed out after {self._timeout}s "
                f"for repository '{owner}/{repo}'."
            ) from exc
        except httpx.RequestError as exc:
            logger.warning("GitHub API request error for %s/%s: %s", owner, repo, exc)
            raise GitHubUpstreamError(
                f"Network error while contacting GitHub for '{owner}/{repo}'."
            ) from exc

        logger.debug("GitHub API response: GET %s → %s", url, response.status_code)

        # ── Status code translation ───────────────────────────────────────────
        if response.status_code == 404:
            raise GitHubRepositoryNotFoundError(
                f"GitHub repository '{owner}/{repo}' was not found. "
                "Verify the repository exists and is public."
            )

        if response.status_code in (403, 429):
            remaining = response.headers.get("x-ratelimit-remaining", "unknown")
            logger.warning(
                "GitHub rate limit hit for %s/%s — remaining=%s", owner, repo, remaining
            )
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded. "
                "Configure a GITHUB_TOKEN to increase the rate limit."
            )

        if response.status_code >= 500:
            logger.error(
                "GitHub upstream error for %s/%s: HTTP %s",
                owner,
                repo,
                response.status_code,
            )
            raise GitHubUpstreamError(
                "GitHub returned an unexpected server error "
                f"(HTTP {response.status_code})."
            )

        if not response.is_success:
            logger.error(
                "Unexpected GitHub response for %s/%s: HTTP %s",
                owner,
                repo,
                response.status_code,
            )
            raise GitHubUpstreamError(
                f"Unexpected response from GitHub (HTTP {response.status_code})."
            )

        # ── Response parsing ──────────────────────────────────────────────────
        try:
            raw: dict[str, object] = response.json()
        except Exception as exc:
            raise GitHubMalformedResponseError(
                "GitHub API response is not valid JSON."
            ) from exc

        try:
            return GitHubRepoData.from_github_json(raw)
        except (ValidationError, KeyError, TypeError) as exc:
            logger.error(
                "Failed to parse GitHub API response for %s/%s: %s", owner, repo, exc
            )
            raise GitHubMalformedResponseError(
                "GitHub API response did not match the expected schema."
            ) from exc
