"""Pydantic schemas for Vector RAG search and retrieval."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class RetrievalMode(StrEnum):
    """Supported retrieval search modes."""

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


class CodeSearchRequest(BaseModel):
    """Payload for code search queries."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Search query string or code symbol.",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of relevant chunks to return.",
    )
    mode: RetrievalMode = Field(
        default=RetrievalMode.HYBRID,
        description="Retrieval mode (hybrid, semantic, or keyword).",
    )
    file_extensions: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Filter results by exact file extensions (e.g. ['.py', '.ts']).",
    )
    file_paths: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Filter results by file path prefix (e.g. ['app/api/']).",
    )
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum normalized relevance score threshold.",
    )

    @field_validator("file_extensions")
    @classmethod
    def normalize_extensions(cls, v: list[str] | None) -> list[str] | None:
        """Ensure file extensions always start with a dot."""
        if not v:
            return v
        return [ext if ext.startswith(".") else f".{ext}" for ext in v]


class ChunkSearchResult(BaseModel):
    """Individual retrieved code chunk result."""

    chunk_id: int
    file_path: str
    start_line: int
    end_line: int
    language: str | None
    chunk_type: str
    name: str | None
    chunk_text: str
    score: float = Field(ge=0.0, le=1.0)
    retrieval_sources: list[str]


class CodeSearchResponse(BaseModel):
    """Complete response payload for a code search query."""

    query: str
    repository_id: int
    ingestion_id: int
    total_results: int
    search_mode: RetrievalMode
    results: list[ChunkSearchResult]
