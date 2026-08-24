"""GitHub repository URL parser and validator.

Provides a single reusable entry-point ``parse_github_url`` that validates,
normalises, and decomposes a GitHub repository URL into its constituent parts.

Security note
-------------
This module is the primary SSRF protection boundary.  Only URLs whose hostname
is exactly ``github.com`` are accepted; any other host is unconditionally
rejected *before* any I/O occurs.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.github.exceptions import InvalidGitHubURLError

_ALLOWED_HOSTNAME = "github.com"
_ALLOWED_SCHEME = "https"


@dataclass(frozen=True)
class GitHubRepoCoords:
    """Decomposed, validated GitHub repository coordinates.

    Attributes
    ----------
    owner:
        The GitHub user or organisation login (e.g. ``"octocat"``).
    repo:
        The repository name without ``.git`` suffix (e.g. ``"Hello-World"``).
    normalized_url:
        Canonical HTTPS URL without trailing slashes or ``.git`` suffix
        (e.g. ``"https://github.com/octocat/Hello-World"``).
    """

    owner: str
    repo: str
    normalized_url: str


def parse_github_url(url: str) -> GitHubRepoCoords:
    """Parse and validate a GitHub repository URL.

    Accepts URLs of the form::

        https://github.com/<owner>/<repository>
        https://github.com/<owner>/<repository>.git
        https://github.com/<owner>/<repository>/

    Parameters
    ----------
    url:
        Raw URL string supplied by the user or stored in the database.

    Returns
    -------
    GitHubRepoCoords
        Validated and normalised repository coordinates.

    Raises
    ------
    InvalidGitHubURLError
        For any URL that does not meet the above criteria, including
        non-HTTPS schemes, non-github.com hosts, missing path segments,
        or unsupported extra path segments.
    """
    if not url or not url.strip():
        raise InvalidGitHubURLError("GitHub URL must not be empty.")

    url = url.strip()

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise InvalidGitHubURLError(f"Malformed URL: {url!r}") from exc

    # ── Scheme check ──────────────────────────────────────────────────────────
    if parsed.scheme != _ALLOWED_SCHEME:
        raise InvalidGitHubURLError(
            f"GitHub URL must use HTTPS (got scheme {parsed.scheme!r}). "
            "Example: https://github.com/owner/repo"
        )

    # ── Hostname check (SSRF protection) ─────────────────────────────────────
    hostname = (parsed.netloc or "").lower().split(":")[0]  # strip port if any
    if hostname != _ALLOWED_HOSTNAME:
        raise InvalidGitHubURLError(
            f"GitHub URL hostname must be 'github.com' (got {hostname!r}). "
            "Only public github.com repositories are supported."
        )

    # ── Path decomposition ────────────────────────────────────────────────────
    path = parsed.path.rstrip("/")
    segments = [s for s in path.split("/") if s]

    if len(segments) < 2:
        raise InvalidGitHubURLError(
            "GitHub URL must contain both an owner and a repository name: "
            "https://github.com/<owner>/<repo>"
        )

    if len(segments) > 2:
        raise InvalidGitHubURLError(
            "GitHub URL must point directly to a repository root with no "
            f"extra path segments (got {len(segments)} segments: {segments!r}). "
            "Example: https://github.com/owner/repo"
        )

    owner, repo = segments[0], segments[1]

    # Strip .git suffix
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise InvalidGitHubURLError(
            "GitHub URL owner and repository name must not be empty."
        )

    normalized_url = f"https://github.com/{owner}/{repo}"
    return GitHubRepoCoords(owner=owner, repo=repo, normalized_url=normalized_url)
