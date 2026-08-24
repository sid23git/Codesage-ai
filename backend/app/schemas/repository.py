"""Pydantic schemas for repository creation, updates, and responses."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.github.exceptions import InvalidGitHubURLError
from app.github.url_parser import parse_github_url


class RepositoryStatus(StrEnum):
    """Lifecycle status of a repository in CodeSage AI."""

    PENDING = "pending"
    READY = "ready"
    ANALYZING = "analyzing"
    FAILED = "failed"


class RepositoryCreate(BaseModel):
    """Schema for repository registration request."""

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Short name of the repository (e.g. 'Codesage-ai').",
    )
    github_url: str = Field(
        min_length=1,
        max_length=1024,
        description="Full GitHub repository URL (https://github.com/owner/repo).",
    )
    description: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional repository description.",
    )
    primary_language: str | None = Field(
        default=None,
        max_length=100,
        description="Primary programming language.",
    )

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        """Validate and normalise the GitHub repository URL.

        Enforces:
        - HTTPS scheme
        - Hostname must be ``github.com`` (SSRF protection)
        - Exactly two path segments (owner/repo)

        Raises
        ------
        ValueError
            With a descriptive message forwarded as a 422 Unprocessable Entity.
        """
        try:
            coords = parse_github_url(v)
        except InvalidGitHubURLError as exc:
            raise ValueError(str(exc)) from exc
        return coords.normalized_url


class RepositoryUpdate(BaseModel):
    """Schema for modifying repository metadata."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated repository name.",
    )
    description: str | None = Field(
        default=None,
        max_length=5000,
        description="Updated description.",
    )
    primary_language: str | None = Field(
        default=None,
        max_length=100,
        description="Updated primary programming language.",
    )
    status: RepositoryStatus | None = Field(
        default=None,
        description="Updated processing status.",
    )


class RepositoryResponse(BaseModel):
    """Schema for repository data returned by API endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    full_name: str
    github_url: str
    description: str | None
    primary_language: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    # GitHub metadata — populated after a successful sync
    github_repository_id: int | None = None
    github_owner: str | None = None
    default_branch: str | None = None
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    github_updated_at: datetime | None = None
    last_synced_at: datetime | None = None
