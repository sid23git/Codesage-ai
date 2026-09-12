"""Pydantic schemas for repository-grounded code review (M6 Phase 4)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.schemas.rag import ChunkSearchResult
from app.schemas.validators import validate_line_range

MAX_USER_CODE_CHARS = 20000


class ReviewFocus(StrEnum):
    """Supported code-review focus areas."""

    GENERAL = "general"
    BUGS = "bugs"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"
    PERFORMANCE = "performance"
    STYLE = "style"


class ReviewRequest(BaseModel):
    """Payload for ``POST /repositories/{id}/review``.

    Requires at least one of ``file_path`` (a repository target) or
    ``user_code`` (untrusted, user-supplied code/diff text) — reviewing
    nothing is not a valid request.
    """

    file_path: str | None = Field(
        default=None,
        max_length=1024,
        description="Repository-relative path of the file to review.",
    )
    symbol: str | None = Field(
        default=None,
        max_length=255,
        description="Optional function/class/symbol name to focus on.",
    )
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    focus: ReviewFocus = Field(
        default=ReviewFocus.GENERAL,
        description="Review focus area.",
    )
    user_code: str | None = Field(
        default=None,
        max_length=MAX_USER_CODE_CHARS,
        description=(
            "Optional user-provided code or diff to review, treated as "
            "untrusted input. Maximum 20,000 characters."
        ),
    )
    conversation_id: int | None = Field(
        default=None,
        description=(
            "Existing conversation to append this review to. Omit to get "
            "a one-off review with no persistence."
        ),
    )

    @model_validator(mode="after")
    def _validate_target(self) -> ReviewRequest:
        if not self.file_path and not self.user_code:
            raise ValueError(
                "Provide at least a file_path target or user_code to review."
            )
        validate_line_range(self.start_line, self.end_line)
        return self


class ReviewFindingResponse(BaseModel):
    """A single structured code-review finding."""

    title: str
    severity: str | None = None
    category: str | None = None
    explanation: str | None = None
    recommendation: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    evidence_chunk_ids: list[int] = Field(default_factory=list)


class ReviewResponse(BaseModel):
    """Response payload for ``POST /repositories/{id}/review``."""

    conversation_id: int | None = None
    status: str
    summary: str
    findings: list[ReviewFindingResponse] = Field(default_factory=list)
    evidence: list[ChunkSearchResult] = Field(default_factory=list)
    model: str | None = None
    ingestion_id: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
