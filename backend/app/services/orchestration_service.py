"""RAG -> LLM orchestration service (Milestone 6, Phases 2 and 4).

Connects M5 retrieval (``RAGService.search()``) to the M6 LLM provider
abstraction (``BaseLLMProvider``) via the token-budgeted ``PromptBuilder``.

This service is intentionally independent of FastAPI: it takes plain
arguments (an ``AsyncSession``, IDs, a question, already-configured
providers) and returns a plain dataclass result, so it can be exercised
directly in tests and reused by API endpoints without any FastAPI-specific
coupling.

Three public entry points share one private ``_run()`` implementation so
none of the RAG-retrieval / prompt-building / LLM-calling / result-
normalizing logic is duplicated across task types:

- ``ask()``     -- free-form repository Q&A (Phase 2/3).
- ``explain()`` -- explain a specific file/symbol/line-range (Phase 4).
- ``review()``  -- structured code review of repository code and/or
  user-provided code/diffs (Phase 4).

Explicitly NOT in this service's scope
----------------------------------------
- Conversation/message persistence (lives in ``ConversationService``).
- API endpoints (live in ``app/api/v1/assistant.py``).
- Streaming (deferred to M7).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.prompt_builder import InsufficientEvidenceError, PromptBuilder
from app.llm.prompt_templates import (
    ASK_SYSTEM_INSTRUCTIONS,
    EXPLAIN_SYSTEM_INSTRUCTIONS,
    REVIEW_SYSTEM_INSTRUCTIONS,
    build_explain_query,
    build_explain_question,
    build_review_query,
    build_review_question,
)
from app.llm.providers.base import BaseLLMProvider, LLMMessage
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.schemas.rag import ChunkSearchResult, CodeSearchRequest, RetrievalMode
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

_DEFAULT_RETRIEVAL_TOP_K = 10
_MAX_USER_CODE_CHARS = 20000

_INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I could not find enough relevant, sufficiently-confident evidence in "
    "this repository's indexed code to answer that question. Try "
    "rephrasing the question, or confirm the repository has been indexed."
)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class RepositoryNotIndexedError(Exception):
    """Raised when the target repository has no completed ingestion yet.

    Translates ``RAGService.search()``'s internal ``ValueError`` signal
    into a stable, orchestration-owned exception type, so callers of this
    service never need to know that M5 happens to use a bare ``ValueError``
    for this condition.
    """


class InvalidReviewTargetError(Exception):
    """Raised when a review request has no reviewable target at all, or
    when user-provided code exceeds the configured size limit.

    The API layer validates both of these at the schema level already;
    this is a defense-in-depth check for any other caller of this service.
    """


@dataclass(frozen=True)
class AssistantAnswer:
    """Provider-agnostic, orchestration-level result of an ``ask()``/
    ``explain()`` call."""

    status: Literal["answered", "insufficient_evidence"]
    answer: str
    evidence: list[ChunkSearchResult] = field(default_factory=list)
    model: str | None = None
    ingestion_id: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ReviewFinding:
    """A single structured code-review finding."""

    title: str
    severity: str | None = None
    category: str | None = None
    explanation: str | None = None
    recommendation: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    evidence_chunk_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewAnswer:
    """Provider-agnostic, orchestration-level result of a ``review()`` call."""

    status: Literal["answered", "insufficient_evidence"]
    summary: str
    findings: list[ReviewFinding] = field(default_factory=list)
    evidence: list[ChunkSearchResult] = field(default_factory=list)
    model: str | None = None
    ingestion_id: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def _parse_review_response(
    raw_text: str, evidence_used: list[ChunkSearchResult]
) -> tuple[str, list[ReviewFinding]]:
    """Leniently parse the LLM's raw review response into structured data.

    The model is instructed (see ``prompt_templates.REVIEW_RESPONSE_FORMAT_
    INSTRUCTIONS``) to reply with a single JSON object, but real models
    sometimes wrap it in a markdown code fence or add stray whitespace.
    If parsing still fails, or the shape is not what was asked for, this
    degrades gracefully to the raw text as the summary with no structured
    findings, rather than raising -- a malformed structured response is
    not a reason to fail the whole review.
    """
    cleaned = _JSON_FENCE_RE.sub("", raw_text.strip()).strip()

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "Review response was not valid JSON; falling back to raw "
            "summary text with no structured findings."
        )
        return raw_text.strip(), []

    if not isinstance(data, dict):
        return raw_text.strip(), []

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = raw_text.strip()

    findings: list[ReviewFinding] = []
    raw_findings = data.get("findings")
    if isinstance(raw_findings, list):
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if not isinstance(title, str) or not title.strip():
                continue

            evidence_chunk_ids: list[int] = []
            sources = item.get("evidence_sources")
            if isinstance(sources, list):
                for n in sources:
                    if isinstance(n, int) and 1 <= n <= len(evidence_used):
                        evidence_chunk_ids.append(evidence_used[n - 1].chunk_id)

            def _str_or_none(value: object) -> str | None:
                return value if isinstance(value, str) and value.strip() else None

            def _int_or_none(value: object) -> int | None:
                return value if isinstance(value, int) else None

            findings.append(
                ReviewFinding(
                    title=title,
                    severity=_str_or_none(item.get("severity")),
                    category=_str_or_none(item.get("category")),
                    explanation=_str_or_none(item.get("explanation")),
                    recommendation=_str_or_none(item.get("recommendation")),
                    file_path=_str_or_none(item.get("file_path")),
                    start_line=_int_or_none(item.get("start_line")),
                    end_line=_int_or_none(item.get("end_line")),
                    evidence_chunk_ids=evidence_chunk_ids,
                )
            )

    return summary, findings


class OrchestrationService:
    """Orchestrates a single RAG-grounded assistant turn (ask/explain/review).

    Stateless service: mirrors ``RAGService``/``IngestionService``/
    ``RepositoryService`` — no instantiation, all dependencies passed
    explicitly per call.
    """

    @classmethod
    async def _run(
        cls,
        *,
        db: AsyncSession,
        repository_id: int,
        owner_id: int,
        search_request: CodeSearchRequest,
        question: str,
        system_instructions: str,
        llm_provider: BaseLLMProvider,
        embedding_provider: BaseEmbeddingProvider,
        token_budget: int,
        min_relevance_score: float,
        max_history_messages: int,
        max_output_tokens: int,
        history: list[LLMMessage] | None,
        require_evidence: bool,
    ) -> AssistantAnswer:
        """Shared RAG -> prompt -> LLM turn used by ask/explain/review.

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

        # RAGService.search()'s own reads autobegin a transaction on this
        # session (SQLAlchemy asyncio sessions autobegin on first execute()
        # and only end it on commit/rollback) that is still open at this
        # point, even though the API layer already closed out whatever
        # transaction its own pre-flight reads had opened before calling
        # us. Close it out here too, before the LLM call below -- no DB
        # transaction may be held open across an external network call.
        # `evidence`/`ingestion_id` above are plain values (a Pydantic
        # schema list and an int), not attached ORM instances, so nothing
        # here depends on the session remaining in that transaction.
        if db.in_transaction():
            await db.commit()

        prompt_builder = PromptBuilder(
            token_budget=token_budget,
            min_relevance_score=min_relevance_score,
            max_history_messages=max_history_messages,
            system_instructions=system_instructions,
        )

        try:
            prompt_result = prompt_builder.build(
                question=question,
                evidence=evidence,
                history=history,
                require_evidence=require_evidence,
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
            Optional prior conversation turns, oldest-first.
        retrieval_top_k:
            How many candidate chunks to request from ``RAGService.search()``.

        Returns
        -------
        AssistantAnswer
        """
        search_request = CodeSearchRequest(
            query=question,
            top_k=retrieval_top_k,
            mode=RetrievalMode.HYBRID,
        )
        return await cls._run(
            db=db,
            repository_id=repository_id,
            owner_id=owner_id,
            search_request=search_request,
            question=question,
            system_instructions=ASK_SYSTEM_INSTRUCTIONS,
            llm_provider=llm_provider,
            embedding_provider=embedding_provider,
            token_budget=token_budget,
            min_relevance_score=min_relevance_score,
            max_history_messages=max_history_messages,
            max_output_tokens=max_output_tokens,
            history=history,
            require_evidence=True,
        )

    @classmethod
    async def explain(
        cls,
        *,
        db: AsyncSession,
        repository_id: int,
        owner_id: int,
        file_path: str,
        llm_provider: BaseLLMProvider,
        embedding_provider: BaseEmbeddingProvider,
        token_budget: int,
        min_relevance_score: float,
        max_history_messages: int,
        max_output_tokens: int,
        start_line: int | None = None,
        end_line: int | None = None,
        symbol: str | None = None,
        question: str | None = None,
        history: list[LLMMessage] | None = None,
        retrieval_top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
    ) -> AssistantAnswer:
        """Explain a specific file/line-range/symbol, grounded in RAG evidence.

        Retrieval is scoped to *file_path* (via ``CodeSearchRequest.
        file_paths``) and, like ``ask()``, requires qualifying evidence —
        if nothing relevant is found for this target, the result is
        ``status="insufficient_evidence"``, never a fabricated explanation.
        """
        query = build_explain_query(
            file_path=file_path, symbol=symbol, question=question
        )
        explain_question = build_explain_question(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            symbol=symbol,
            question=question,
        )
        search_request = CodeSearchRequest(
            query=query,
            top_k=retrieval_top_k,
            mode=RetrievalMode.HYBRID,
            file_paths=[file_path],
        )
        return await cls._run(
            db=db,
            repository_id=repository_id,
            owner_id=owner_id,
            search_request=search_request,
            question=explain_question,
            system_instructions=EXPLAIN_SYSTEM_INSTRUCTIONS,
            llm_provider=llm_provider,
            embedding_provider=embedding_provider,
            token_budget=token_budget,
            min_relevance_score=min_relevance_score,
            max_history_messages=max_history_messages,
            max_output_tokens=max_output_tokens,
            history=history,
            require_evidence=True,
        )

    @classmethod
    async def review(
        cls,
        *,
        db: AsyncSession,
        repository_id: int,
        owner_id: int,
        focus: str,
        llm_provider: BaseLLMProvider,
        embedding_provider: BaseEmbeddingProvider,
        token_budget: int,
        min_relevance_score: float,
        max_history_messages: int,
        max_output_tokens: int,
        file_path: str | None = None,
        symbol: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        user_code: str | None = None,
        history: list[LLMMessage] | None = None,
        retrieval_top_k: int = _DEFAULT_RETRIEVAL_TOP_K,
    ) -> ReviewAnswer:
        """Review repository code and/or user-provided code, grounded in
        RAG evidence, returning structured findings.

        Exactly one of *file_path* or *user_code* must be given (enforced
        by the caller's request schema; re-checked here defensively).
        When *user_code* is provided, repository evidence is treated as
        optional supporting context rather than a hard requirement — the
        user's own submitted code is the primary review subject, so a
        lack of closely-matching indexed evidence must not block
        reviewing it. When only a repository target is given (no
        *user_code*), the same evidence-required policy as ``ask()``/
        ``explain()`` applies.

        Raises
        ------
        InvalidReviewTargetError
            If neither *file_path* nor *user_code* is given, or
            *user_code* exceeds the configured maximum size.
        (plus everything ``_run()`` can raise)
        """
        if not file_path and not user_code:
            raise InvalidReviewTargetError(
                "Provide at least a file_path target or user_code to review."
            )
        if user_code is not None and len(user_code) > _MAX_USER_CODE_CHARS:
            raise InvalidReviewTargetError(
                f"user_code exceeds the maximum of {_MAX_USER_CODE_CHARS} characters."
            )

        query = build_review_query(
            file_path=file_path, symbol=symbol, user_code=user_code
        )
        review_question = build_review_question(
            focus=focus,
            file_path=file_path,
            symbol=symbol,
            start_line=start_line,
            end_line=end_line,
            user_code=user_code,
        )
        search_request = CodeSearchRequest(
            query=query,
            top_k=retrieval_top_k,
            mode=RetrievalMode.HYBRID,
            file_paths=[file_path] if file_path else None,
        )
        require_evidence = user_code is None

        answer = await cls._run(
            db=db,
            repository_id=repository_id,
            owner_id=owner_id,
            search_request=search_request,
            question=review_question,
            system_instructions=REVIEW_SYSTEM_INSTRUCTIONS,
            llm_provider=llm_provider,
            embedding_provider=embedding_provider,
            token_budget=token_budget,
            min_relevance_score=min_relevance_score,
            max_history_messages=max_history_messages,
            max_output_tokens=max_output_tokens,
            history=history,
            require_evidence=require_evidence,
        )

        if answer.status == "insufficient_evidence":
            return ReviewAnswer(
                status="insufficient_evidence",
                summary=answer.answer,
                ingestion_id=answer.ingestion_id,
            )

        summary, findings = _parse_review_response(answer.answer, answer.evidence)
        return ReviewAnswer(
            status="answered",
            summary=summary,
            findings=findings,
            evidence=answer.evidence,
            model=answer.model,
            ingestion_id=answer.ingestion_id,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
        )
