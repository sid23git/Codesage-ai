"""Pydantic schemas for M6 conversations, messages, and assistant responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.rag import ChunkSearchResult


class AskRequest(BaseModel):
    """Payload for ``POST /repositories/{id}/ask``."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The user's question about the repository.",
    )
    conversation_id: int | None = Field(
        default=None,
        description=(
            "Existing conversation to continue. Omit to start a new "
            "conversation for this repository."
        ),
    )


class EvidenceCitation(BaseModel):
    """A single soft-referenced evidence citation persisted on a Message.

    Deliberately not a foreign key to ``code_chunks`` — see
    ``app.models.conversation.Message`` for why — so this shape survives
    repository re-indexing intact.
    """

    chunk_id: int
    file_path: str
    start_line: int
    end_line: int
    language: str | None = None
    name: str | None = None
    score: float
    snippet: str


class MessageResponse(BaseModel):
    """A single persisted conversation message."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    evidence: list[EvidenceCitation] | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: datetime


class ConversationSummaryResponse(BaseModel):
    """A conversation without its full message history (list view)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: int
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationSummaryResponse):
    """A conversation including its full, chronologically-ordered history."""

    messages: list[MessageResponse] = Field(default_factory=list)


class AskResponse(BaseModel):
    """Response payload for ``POST /repositories/{id}/ask``.

    ``evidence`` here is the *live* ``ChunkSearchResult`` set returned by
    this turn's retrieval (full chunk text, not the bounded snippet that
    gets persisted) — see ``ConversationService`` for the distinction.
    """

    conversation_id: int
    status: str
    answer: str
    evidence: list[ChunkSearchResult] = Field(default_factory=list)
    model: str | None = None
    ingestion_id: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
