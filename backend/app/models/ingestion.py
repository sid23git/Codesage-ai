"""Repository ingestion SQLAlchemy ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.repository import Repository

# Use JSONB for PostgreSQL when available, fallback to standard JSON for SQLite
JSONType = JSON().with_variant(JSONB, "postgresql")


class RepositoryIngestion(Base):
    """Repository ingestion record entity.

    Represents a specific ingestion run for a repository, tracking its lifecycle
    status, discovered source file metrics, detected language breakdown,
    directory structure summary, and safe error details.
    """

    __tablename__ = "repository_ingestions"

    # ── Identity & Foreign Key ────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Ingestion Status & Revision ───────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        nullable=False,
        index=True,
        comment="Ingestion status: pending | ingesting | completed | failed",
    )
    commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="Commit SHA or reference of the ingested source snapshot.",
    )

    # ── Discovered Source Metrics ─────────────────────────────────────────────
    file_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Total count of accepted source files discovered.",
    )
    total_size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
        comment="Total uncompressed size of accepted source files in bytes.",
    )
    total_lines: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Total line count across all accepted text source files.",
    )
    primary_language: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Primary programming language determined from source files.",
    )

    # ── Structural Analysis & Catalog (JSON) ──────────────────────────────────
    language_stats: Mapped[dict[str, Any] | None] = mapped_column(
        JSONType,
        nullable=True,
        comment="Per-language breakdown with file counts, byte sizes, and line counts.",
    )
    directory_summary: Mapped[dict[str, int] | None] = mapped_column(
        JSONType,
        nullable=True,
        comment="Top-level and nested directory file distribution.",
    )
    file_catalog: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONType,
        nullable=True,
        comment="Detailed catalog of accepted source files and their metadata.",
    )

    # ── Error Reporting (User-Safe) ───────────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Sanitized, user-safe error message if ingestion failed.",
    )

    # ── Lifecycle Timestamps ──────────────────────────────────────────────────
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when ingestion processing began.",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when ingestion reached a terminal state (completed/failed).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    repository: Mapped[Repository] = relationship(
        "Repository",
        back_populates="ingestions",
    )

    def __repr__(self) -> str:
        return (
            f"<RepositoryIngestion id={self.id} repository_id={self.repository_id} "
            f"status={self.status!r} file_count={self.file_count}>"
        )
