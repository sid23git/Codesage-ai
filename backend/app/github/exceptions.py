"""Typed exception hierarchy for GitHub integration errors.

All exceptions inherit from ``GitHubIntegrationError`` so callers can catch
the base class for blanket handling, or individual subclasses for fine-grained
responses.
"""

from __future__ import annotations


class GitHubIntegrationError(Exception):
    """Base class for all GitHub integration failures."""


class InvalidGitHubURLError(GitHubIntegrationError):
    """Raised when a supplied URL is not a valid public GitHub repository URL.

    Examples of invalid input:
    - Non-HTTPS scheme (``http://``, ``git://``)
    - Hostname is not ``github.com``
    - Missing owner or repository path segment
    - Extra unsupported path segments
    """


class GitHubRepositoryNotFoundError(GitHubIntegrationError):
    """Raised when the GitHub API returns 404 for a repository lookup."""


class GitHubRateLimitError(GitHubIntegrationError):
    """Raised when GitHub API signals a rate-limit (exhausted quota)."""


class GitHubUpstreamError(GitHubIntegrationError):
    """Raised when the GitHub API returns an unexpected 5xx server error."""


class GitHubTimeoutError(GitHubIntegrationError):
    """Raised when an outbound request to GitHub exceeds the configured timeout."""


class GitHubMalformedResponseError(GitHubIntegrationError):
    """Raised when the GitHub API response cannot be parsed into the expected schema."""
