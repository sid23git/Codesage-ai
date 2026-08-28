"""Pydantic schemas for repository ingestion requests, responses, and metrics."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IngestionStatus(StrEnum):
    """Lifecycle status of a repository ingestion run."""

    PENDING = "pending"
    INGESTING = "ingesting"
    COMPLETED = "completed"
    FAILED = "failed"


class FileMetadata(BaseModel):
    """Metadata extracted for an individual discovered source file."""

    model_config = ConfigDict(from_attributes=True)

    path: str = Field(
        description="Relative file path within the repo root (e.g. 'src/main.py')."
    )
    name: str = Field(description="File name with extension (e.g. 'main.py').")
    extension: str = Field(
        description="Lowercase file extension including dot (e.g. '.py')."
    )
    language: str | None = Field(
        default=None, description="Detected programming or markup language."
    )
    size_bytes: int = Field(description="File size in bytes.")
    line_count: int | None = Field(
        default=None,
        description="Line count for text-based source files (None for binaries).",
    )


class LanguageStat(BaseModel):
    """Aggregated metrics for a specific programming language."""

    model_config = ConfigDict(from_attributes=True)

    files: int = Field(description="Number of accepted files in this language.")
    bytes: int = Field(description="Total bytes across all files in this language.")
    lines: int = Field(description="Total lines across all files in this language.")


class IngestionResponse(BaseModel):
    """Detailed response schema for a repository ingestion run."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: int
    status: str
    commit_sha: str | None = None
    file_count: int = 0
    total_size_bytes: int = 0
    total_lines: int = 0
    primary_language: str | None = None
    language_stats: dict[str, Any] | None = None
    directory_summary: dict[str, int] | None = None
    file_catalog: list[dict[str, Any]] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IngestionSummaryResponse(BaseModel):
    """Concise response schema for listing historical ingestion runs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: int
    status: str
    commit_sha: str | None = None
    file_count: int = 0
    total_size_bytes: int = 0
    total_lines: int = 0
    primary_language: str | None = None
    language_stats: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
