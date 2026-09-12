"""Conversation/message persistence service (Milestone 6, Phase 3).

Owns the lifecycle of ``Conversation``/``Message`` rows: creation,
ownership verification, history loading for the LLM, and turn persistence.
RAG/LLM orchestration itself lives in ``OrchestrationService`` and is never
touched here — this service only ever performs database reads/writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.providers.base import LLMMessage
from app.models.conversation import Conversation, Message
from app.schemas.rag import ChunkSearchResult
from app.services.orchestration_service import AssistantAnswer

# Evidence persisted on a Message is a bounded snippet, not the full
# retrieved chunk text — this keeps stored history compact regardless of
# how large the original chunk was. The *live* AskResponse returned at
# ask-time still carries the full ChunkSearchResult set (see AskResponse).
_EVIDENCE_SNIPPET_MAX_CHARS = 500


class ConversationService:
    """Service layer managing ``Conversation``/``Message`` persistence."""

    @classmethod
    async def create_conversation(
        cls, db: AsyncSession, user_id: int, repository_id: int
    ) -> Conversation:
        """Create a new, empty conversation owned by *user_id*."""
        conversation = Conversation(user_id=user_id, repository_id=repository_id)
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        return conversation

    @classmethod
    async def get_owned_conversation(
        cls,
        db: AsyncSession,
        user_id: int,
        repository_id: int,
        conversation_id: int,
    ) -> Conversation | None:
        """Return the conversation only if owned by *user_id* and scoped to
        *repository_id* — never leaks another user's or another
        repository's conversation, even to a caller who guesses a valid ID.
        """
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.repository_id == repository_id,
            )
        )
        return result.scalars().first()

    @classmethod
    async def list_conversations(
        cls, db: AsyncSession, user_id: int, repository_id: int
    ) -> list[Conversation]:
        """Return all conversations owned by *user_id* for *repository_id*,
        most recently active first.
        """
        result = await db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.repository_id == repository_id,
            )
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    def build_history(
        conversation: Conversation, max_history_messages: int
    ) -> list[LLMMessage]:
        """Convert up to the most recent *max_history_messages* persisted
        messages into provider-agnostic ``LLMMessage``s, oldest-first.

        Called with the conversation as it stood *before* the current
        turn — the new question is passed to ``OrchestrationService.ask()``
        separately, not included here.
        """
        if max_history_messages <= 0:
            return []
        recent = conversation.messages[-max_history_messages:]
        return [LLMMessage(role=m.role, content=m.content) for m in recent]  # type: ignore[arg-type]

    @staticmethod
    def _serialize_evidence(chunks: list[ChunkSearchResult]) -> list[dict[str, Any]]:
        """Capture a soft (non-FK) evidence snapshot for historical citation.

        See ``app.models.conversation.Message.evidence`` for why this is a
        JSON snapshot rather than a foreign key.
        """
        return [
            {
                "chunk_id": chunk.chunk_id,
                "file_path": chunk.file_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "language": chunk.language,
                "name": chunk.name,
                "score": chunk.score,
                "snippet": chunk.chunk_text[:_EVIDENCE_SNIPPET_MAX_CHARS],
            }
            for chunk in chunks
        ]

    @classmethod
    async def record_turn(
        cls,
        db: AsyncSession,
        conversation: Conversation,
        *,
        user_content: str,
        answer: AssistantAnswer,
    ) -> tuple[Message, Message]:
        """Persist the user question and assistant answer together.

        ``conversation`` may be either a brand-new, not-yet-persisted
        instance (no ``id`` yet — a new conversation for this turn) or an
        existing, already-persisted one. Either way, this is the *only*
        point at which a new conversation is actually written to the
        database: if the caller passes a transient ``Conversation`` and
        the LLM call fails before this method is reached, no conversation
        row is ever created, so a failed first turn never leaves an
        orphaned, empty conversation behind.

        Must be called *after* RAG retrieval and the LLM call have already
        completed — this method performs no external network calls or slow
        work itself, only the DB writes, kept inside one short, bounded
        transaction (mirrors ``app.services.rag_service``'s Phase 3
        pattern).
        """
        user_message = Message(role="user", content=user_content)
        assistant_message = Message(
            role="assistant",
            content=answer.answer,
            evidence=cls._serialize_evidence(answer.evidence),
            model=answer.model,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
        )
        # Appending (rather than setting conversation_id explicitly) lets
        # cascade="all, ..." (which includes save-update) insert a brand
        # new conversation and its first two messages together, or attach
        # to an already-persisted conversation identically either way.
        conversation.messages.append(user_message)
        conversation.messages.append(assistant_message)

        # Guarantee this persist step is a single, short, self-contained
        # transaction regardless of what state the caller's session was
        # already in.
        if db.in_transaction():
            await db.commit()

        async with db.begin():
            db.add(conversation)
            conversation.updated_at = datetime.now(UTC)

        await db.refresh(user_message)
        await db.refresh(assistant_message)
        return user_message, assistant_message
