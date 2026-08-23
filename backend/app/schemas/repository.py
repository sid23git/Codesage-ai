"""Pydantic schemas for repository creation, updates, and responses."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
        description="Full GitHub repository URL.",
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
        """Ensure github_url is a well-formed HTTP/HTTPS URL."""
        v = v.strip()
        parsed = urlparse(v)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            raise ValueError("github_url must start with http:// or https://")
        if not parsed.netloc:
            raise ValueError("github_url must contain a valid domain name")
        return v


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
