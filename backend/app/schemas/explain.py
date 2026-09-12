"""Pydantic schemas for repository-grounded code explanation (M6 Phase 4)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.schemas.rag import ChunkSearchResult
from app.schemas.validators import validate_line_range


class ExplainRequest(BaseModel):
    """Payload for ``POST /repositories/{id}/explain``."""

    file_path: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Repository-relative path of the file to explain.",
    )
    start_line: int | None = Field(
        default=None, ge=1, description="Optional starting line of the target range."
    )
    end_line: int | None = Field(
        default=None, ge=1, description="Optional ending line of the target range."
    )
    symbol: str | None = Field(
        default=None,
        max_length=255,
        description="Optional function/class/symbol name to focus on.",
    )
    question: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional specific question or focus for the explanation.",
    )
    conversation_id: int | None = Field(
        default=None,
        description=(
            "Existing conversation to append this explanation to. Omit to "
            "get a one-off explanation with no persistence."
        ),
    )

    @model_validator(mode="after")
    def _validate_line_range(self) -> ExplainRequest:
        validate_line_range(self.start_line, self.end_line)
        return self


class ExplainResponse(BaseModel):
    """Response payload for ``POST /repositories/{id}/explain``."""

    conversation_id: int | None = None
    status: str
    explanation: str
    evidence: list[ChunkSearchResult] = Field(default_factory=list)
    model: str | None = None
    ingestion_id: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
