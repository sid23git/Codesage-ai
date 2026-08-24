"""Unit tests for the GitHub URL parser (app/github/url_parser.py).

No network calls are made in these tests.
"""

from __future__ import annotations

import pytest

from app.github.exceptions import InvalidGitHubURLError
from app.github.url_parser import GitHubRepoCoords, parse_github_url


class TestParseGitHubUrlValid:
    """Happy-path tests for valid GitHub URLs."""

    def test_canonical_url(self) -> None:
        """Standard https://github.com/owner/repo is accepted."""
        coords = parse_github_url("https://github.com/octocat/Hello-World")
        assert coords == GitHubRepoCoords(
            owner="octocat",
            repo="Hello-World",
            normalized_url="https://github.com/octocat/Hello-World",
        )

    def test_trailing_slash_stripped(self) -> None:
        """Trailing slash is stripped and URL is normalised."""
        coords = parse_github_url("https://github.com/octocat/Hello-World/")
        assert coords.normalized_url == "https://github.com/octocat/Hello-World"

    def test_git_suffix_stripped(self) -> None:
        """.git suffix is stripped from repo name."""
        coords = parse_github_url("https://github.com/octocat/Hello-World.git")
        assert coords.repo == "Hello-World"
        assert coords.normalized_url == "https://github.com/octocat/Hello-World"

    def test_git_suffix_and_trailing_slash_stripped(self) -> None:
        """Both .git suffix and trailing slash are stripped."""
        coords = parse_github_url("https://github.com/octocat/Hello-World.git/")
        assert coords.repo == "Hello-World"

    def test_owner_and_repo_extracted(self) -> None:
        """Owner and repo are correctly extracted."""
        coords = parse_github_url("https://github.com/sid23git/Codesage-ai")
        assert coords.owner == "sid23git"
        assert coords.repo == "Codesage-ai"

    def test_hyphenated_names(self) -> None:
        """Hyphens in owner and repo names are handled."""
        coords = parse_github_url("https://github.com/my-org/my-cool-repo")
        assert coords.owner == "my-org"
        assert coords.repo == "my-cool-repo"


class TestParseGitHubUrlInvalid:
    """Rejection tests for malformed or unsupported URLs."""

    def test_http_scheme_rejected(self) -> None:
        """http:// (non-HTTPS) is rejected."""
        with pytest.raises(InvalidGitHubURLError, match="HTTPS"):
            parse_github_url("http://github.com/owner/repo")

    def test_git_scheme_rejected(self) -> None:
        """git:// scheme is rejected."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("git://github.com/owner/repo")

    def test_non_github_host_rejected(self) -> None:
        """Non github.com hostname is rejected (SSRF protection)."""
        with pytest.raises(InvalidGitHubURLError, match=r"github\.com"):
            parse_github_url("https://gitlab.com/owner/repo")

    def test_evil_host_rejected(self) -> None:
        """Attacker-controlled hostname is rejected."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://evil.com/owner/repo")

    def test_missing_repo_segment_rejected(self) -> None:
        """URL with only owner and no repo is rejected."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://github.com/octocat")

    def test_root_url_rejected(self) -> None:
        """Bare github.com root URL is rejected."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("https://github.com/")

    def test_extra_path_segments_rejected(self) -> None:
        """URLs with extra path segments (e.g. /tree/main) are rejected."""
        with pytest.raises(InvalidGitHubURLError, match="extra path"):
            parse_github_url("https://github.com/owner/repo/tree/main")

    def test_empty_string_rejected(self) -> None:
        """Empty string is rejected."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("")

    def test_whitespace_only_rejected(self) -> None:
        """Whitespace-only string is rejected."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("   ")

    def test_ftp_scheme_rejected(self) -> None:
        """ftp:// scheme is rejected."""
        with pytest.raises(InvalidGitHubURLError):
            parse_github_url("ftp://github.com/owner/repo")
