"""RAG -> LLM orchestration service (Milestone 6, Phase 2).

Connects M5 retrieval (``RAGService.search()``) to the M6 LLM provider
abstraction (``BaseLLMProvider``) via the token-budgeted ``PromptBuilder``.

This service is intentionally independent of FastAPI: it takes plain
arguments (an ``AsyncSession``, IDs, a question, already-configured
providers) and returns a plain dataclass result, so it can be exercised
directly in tests and reused by API endpoints in a later phase without any
FastAPI-specific coupling.

Explicitly NOT in this phase's scope
-------------------------------------
- Conversation/message persistence (Phase 3).
- API endpoints (Phase 3).
- Streaming (deferred to M7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.prompt_builder import InsufficientEvidenceError, PromptBuilder
from app.llm.providers.base import BaseLLMProvider, LLMMessage
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.schemas.rag import ChunkSearchResult, CodeSearchRequest, RetrievalMode
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

_DEFAULT_RETRIEVAL_TOP_K = 10

_INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I could not find enough relevant, sufficiently-confident evidence in "
    "this repository's indexed code to answer that question. Try "
    "rephrasing the question, or confirm the repository has been indexed."
)


class RepositoryNotIndexedError(Exception):
    """Raised when the target repository has no completed ingestion yet.

    Translates ``RAGService.search()``'s internal ``ValueError`` signal
    into a stable, orchestration-owned exception type, so callers of this
    service never need to know that M5 happens to use a bare ``ValueError``
    for this condition.
    """


@dataclass(frozen=True)
class AssistantAnswer:
    """Provider-agnostic, orchestration-level result of an ``ask()`` call."""

    status: Literal["answered", "insufficient_evidence"]
    answer: str
    evidence: list[ChunkSearchResult] = field(default_factory=list)
    model: str | None = None
    ingestion_id: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class OrchestrationService:
    """Orchestrates a single RAG-grounded question/answer turn.

    Stateless service: mirrors ``RAGService``/``IngestionService``/
    ``RepositoryService`` — no instantiation, all dependencies passed
    explicitly per call.
    """

    @classmethod
    async def ask(
        cls,
        *,
        db: AsyncSession,
        repository_id: int,
        owner_id: int,
        question: str,
        llm_provider: BaseLLMProvider,
        embedding_provider: BaseEmbeddingProvider,
        token_budget: int,
        min_relevance_score: float,
        max_history_messages: int,
        max_output_tokens: int,
        history: list[LLMMessage] | None = None,
        retrieval_top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
    ) -> AssistantAnswer:
        """Answer *question* about *repository_id*, grounded in RAG evidence.

        Parameters
        ----------
        db:
            Async database session (passed straight through to
            ``RAGService.search()`` — this service never touches
            ``CodeChunk``/pgvector/retrieval internals directly).
        repository_id, owner_id:
            Ownership of *repository_id* by *owner_id* must already be
            verified by the caller before this method is invoked, exactly
            as ``RAGService.search()`` itself requires.
        question:
            The current user question.
        llm_provider:
            A configured ``BaseLLMProvider`` (Anthropic, Mock, ...).
        embedding_provider:
            A configured ``BaseEmbeddingProvider``, forwarded to
            ``RAGService.search()`` for query vectorisation.
        token_budget, min_relevance_score, max_history_messages,
        max_output_tokens:
            Resolved configuration values (normally
            ``settings.LLM_CONTEXT_TOKEN_BUDGET``,
            ``settings.LLM_MIN_RELEVANCE_SCORE``,
            ``settings.LLM_MAX_HISTORY_MESSAGES``,
            ``settings.LLM_MAX_OUTPUT_TOKENS`` respectively) — passed
            explicitly rather than read from settings here, so this
            service has no direct dependency on ``app.core.config``.
        history:
            Optional prior conversation turns, oldest-first. Persistence
            of this history is out of scope for this phase; a future
            phase will load it from a ``Message`` table and pass it in
            unchanged.
        retrieval_top_k:
            How many candidate chunks to request from ``RAGService.search()``.

        Returns
        -------
        AssistantAnswer

        Raises
        ------
        RepositoryNotIndexedError
            If the repository has no completed ingestion.
        LLMContextError
            If the question alone (before any evidence/history) exceeds
            the token budget.
        LLMTimeoutError, LLMRateLimitError, LLMConfigurationError,
        LLMProviderError
            Propagated as-is from ``llm_provider.complete()`` — already
            provider-agnostic (see ``app.llm.exceptions``), so this
            service does not need to catch or re-wrap them further.
        """
        search_request = CodeSearchRequest(
            query=question,
            top_k=retrieval_top_k,
            mode=RetrievalMode.HYBRID,
        )

        try:
            evidence, ingestion_id = await RAGService.search(
                db=db,
                request=search_request,
                repository_id=repository_id,
                owner_id=owner_id,
                embedding_provider=embedding_provider,
            )
        except ValueError as exc:
            raise RepositoryNotIndexedError(str(exc)) from exc

        prompt_builder = PromptBuilder(
            token_budget=token_budget,
            min_relevance_score=min_relevance_score,
            max_history_messages=max_history_messages,
        )

        try:
            prompt_result = prompt_builder.build(
                question=question, evidence=evidence, history=history
            )
        except InsufficientEvidenceError:
            logger.info(
                "Insufficient evidence for repository_id=%s ingestion_id=%s "
                "(%d candidate chunks retrieved); not calling the LLM.",
                repository_id,
                ingestion_id,
                len(evidence),
            )
            return AssistantAnswer(
                status="insufficient_evidence",
                answer=_INSUFFICIENT_EVIDENCE_MESSAGE,
                ingestion_id=ingestion_id,
            )
        # LLMContextError intentionally propagates uncaught here: an
        # unrecoverable "the question/system prompt alone is too large"
        # condition the caller must see distinctly, not a case this
        # service can paper over.

        llm_response = await llm_provider.complete(
            prompt_result.messages,
            max_tokens=max_output_tokens,
        )

        return AssistantAnswer(
            status="answered",
            answer=llm_response.content,
            evidence=prompt_result.evidence_used,
            model=llm_response.model,
            ingestion_id=ingestion_id,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
        )
