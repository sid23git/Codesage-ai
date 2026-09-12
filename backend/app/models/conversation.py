"""Conversation and Message SQLAlchemy ORM models (Milestone 6, Phase 3)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.user import User

# Use JSONB for PostgreSQL when available, fallback to standard JSON for SQLite
JSONType = JSON().with_variant(JSONB, "postgresql")


class Conversation(Base):
    """A multi-turn assistant conversation.

    Owned by exactly one user and scoped to exactly one repository — a
    conversation about repository A can never surface repository B's
    context, and can never be read by anyone but the user who owns it.
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="conversations")
    repository: Mapped[Repository] = relationship(
        "Repository", back_populates="conversations"
    )
    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_conversations_user_repository", "user_id", "repository_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation id={self.id} user_id={self.user_id} "
            f"repository_id={self.repository_id}>"
        )


class Message(Base):
    """A single turn (user question or assistant answer) in a Conversation.

    ``evidence`` is a *soft* (non-foreign-key) JSON reference: a snapshot
    of the RAG evidence cited for an assistant answer, captured at the
    moment the answer was generated. It intentionally does not reference
    ``code_chunks.id`` via a foreign key, because M5 re-indexing deletes
    and replaces ``CodeChunk`` rows — a hard FK would either block that
    cleanup or cascade-delete conversation history on every re-index.
    Storing the citation metadata (location, symbol, score) plus a bounded
    text snippet directly keeps historical citations readable regardless
    of what happens to the underlying chunk later.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Message role: user | assistant"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONType,
        nullable=True,
        comment="Soft JSON snapshot of cited RAG evidence (no FK to code_chunks).",
    )

    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="LLM model identifier that generated this message (assistant only).",
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} conversation_id={self.conversation_id} "
            f"role={self.role!r}>"
        )
