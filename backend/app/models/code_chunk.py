"""Code chunk SQLAlchemy ORM model for vector RAG retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.ingestion import RepositoryIngestion
    from app.models.repository import Repository


class CodeChunk(Base):
    """Code chunk entity with vector embeddings.

    Represents a specific chunk of source code (function, class, block)
    with a 1536-dimensional embedding vector for semantic search.
    """

    __tablename__ = "code_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    repository_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )

    ingestion_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("repository_ingestions.id", ondelete="CASCADE"),
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(50), default="block", nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    # 1536-dimensional pgvector column for OpenAI embeddings
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    repository: Mapped[Repository] = relationship(
        "Repository",
        back_populates="code_chunks",
    )
    ingestion: Mapped[RepositoryIngestion] = relationship(
        "RepositoryIngestion",
        back_populates="code_chunks",
    )

    __table_args__ = (
        Index("ix_code_chunks_repo_ingestion", "repository_id", "ingestion_id"),
        Index("ix_code_chunks_repo_file", "repository_id", "file_path"),
        Index("ix_code_chunks_repo_name", "repository_id", "name"),
        # HNSW and GIN tsvector indexes will be created explicitly in Alembic
    )

    def __repr__(self) -> str:
        return (
            f"<CodeChunk id={self.id} file_path={self.file_path!r} "
            f"name={self.name!r} type={self.chunk_type!r}>"
        )
