"""Assistant API endpoints: RAG-grounded Q&A over an indexed repository.

Endpoints here are intentionally thin — all business logic (ownership
verification, RAG->LLM orchestration, persistence) lives in
``OrchestrationService`` / ``ConversationService``. This module's only job
is auth, HTTP-shaped request/response translation, and mapping domain
exceptions to HTTP status codes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_embedding_provider, get_llm_provider
from app.core.config import get_settings
from app.db.session import get_db
from app.llm.exceptions import (
    LLMConfigurationError,
    LLMContextError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.providers.base import BaseLLMProvider
from app.models.conversation import Conversation
from app.models.user import User
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.schemas.conversation import (
    AskRequest,
    AskResponse,
    ConversationDetailResponse,
    ConversationSummaryResponse,
)
from app.schemas.explain import ExplainRequest, ExplainResponse
from app.schemas.review import ReviewFindingResponse, ReviewRequest, ReviewResponse
from app.services.conversation_service import ConversationService
from app.services.orchestration_service import (
    AssistantAnswer,
    InvalidReviewTargetError,
    OrchestrationService,
    RepositoryNotIndexedError,
)
from app.services.repository_service import RepositoryService

router = APIRouter(prefix="/repositories", tags=["assistant"])


async def _resolve_optional_conversation(
    db: AsyncSession,
    user_id: int,
    repository_id: int,
    conversation_id: int | None,
) -> Conversation | None:
    """Resolve an optional conversation_id for explain/review requests.

    Unlike ``/ask`` (which always operates within a conversation, creating
    one when omitted), explain/review are primarily one-off analyses:
    supplying ``conversation_id`` opts into appending the turn to an
    existing, owned, repository-scoped conversation; omitting it means no
    conversation is touched or created at all.
    """
    if conversation_id is None:
        return None

    conversation = await ConversationService.get_owned_conversation(
        db, user_id, repository_id, conversation_id
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


def _raise_for_llm_error(exc: Exception) -> None:
    """Map the shared M6 LLM/orchestration exception taxonomy to HTTP.

    Shared by /ask, /explain, and /review so the mapping (and the status
    codes returned to clients) stays identical across all three endpoints.
    """
    if isinstance(exc, RepositoryNotIndexedError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if isinstance(exc, LLMContextError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if isinstance(exc, LLMTimeoutError):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)
        ) from exc
    if isinstance(exc, LLMRateLimitError):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    if isinstance(exc, (LLMConfigurationError, LLMProviderError)):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    raise exc


@router.post(
    "/{repository_id}/ask",
    response_model=AskResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask the repository assistant a question",
    description=(
        "Ask a RAG-grounded question about an owned, indexed repository. "
        "Creates a new conversation when conversation_id is omitted, or "
        "continues an existing one owned by the caller and scoped to this "
        "repository. Returns a defined insufficient-evidence result "
        "rather than an unsupported answer when the repository has no "
        "sufficiently relevant indexed code for the question."
    ),
)
async def ask_assistant(
    repository_id: int,
    ask_request: AskRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm_provider: Annotated[BaseLLMProvider, Depends(get_llm_provider)],
    embedding_provider: Annotated[
        BaseEmbeddingProvider, Depends(get_embedding_provider)
    ],
) -> AskResponse:
    """Ask a question, grounded in ``RAGService.search()`` evidence.

    Raises
    ------
    HTTPException (404)
        Repository not found/not owned, conversation not found/not owned/
        not scoped to this repository, or the repository has no completed
        ingestion yet.
    HTTPException (422)
        The question alone is too large to fit the configured context
        budget.
    HTTPException (429)
        The LLM provider rate-limited the request.
    HTTPException (502)
        The LLM provider failed or is misconfigured.
    HTTPException (504)
        The LLM provider timed out.
    """
    repo = await RepositoryService.get_repository(db, current_user.id, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    if ask_request.conversation_id is not None:
        conversation = await ConversationService.get_owned_conversation(
            db, current_user.id, repository_id, ask_request.conversation_id
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
    else:
        # Not persisted here -- a brand-new conversation is only written
        # to the database inside record_turn(), together with its first
        # two messages, once we know the turn actually produced a result.
        # This guarantees a failed turn (LLM timeout, no ingestion, etc.)
        # never leaves an orphaned, empty conversation behind.
        conversation = Conversation(
            user_id=current_user.id, repository_id=repository_id
        )

    settings = get_settings()
    history = ConversationService.build_history(
        conversation, settings.LLM_MAX_HISTORY_MESSAGES
    )

    # Close out any transaction opened by the reads above BEFORE the slow
    # RAG retrieval / embedding / LLM calls below -- no database
    # transaction may be held open across external network operations
    # (mirrors the pattern established in app/services/rag_service.py and
    # app/services/ingestion_service.py).
    if db.in_transaction():
        await db.commit()

    try:
        answer = await OrchestrationService.ask(
            db=db,
            repository_id=repo.id,
            owner_id=current_user.id,
            question=ask_request.message,
            llm_provider=llm_provider,
            embedding_provider=embedding_provider,
            token_budget=settings.LLM_CONTEXT_TOKEN_BUDGET,
            min_relevance_score=settings.LLM_MIN_RELEVANCE_SCORE,
            max_history_messages=settings.LLM_MAX_HISTORY_MESSAGES,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            history=history,
        )
    except RepositoryNotIndexedError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except LLMContextError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except LLMRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    # Persist the turn (both the insufficient-evidence and answered cases
    # reach here — only a raised exception above skips persistence, so a
    # failed turn never leaves a dangling user message with no reply).
    await ConversationService.record_turn(
        db,
        conversation,
        user_content=ask_request.message,
        answer=answer,
    )

    return AskResponse(
        conversation_id=conversation.id,
        status=answer.status,
        answer=answer.answer,
        evidence=answer.evidence,
        model=answer.model,
        ingestion_id=answer.ingestion_id,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
    )


@router.get(
    "/{repository_id}/conversations",
    response_model=list[ConversationSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List repository conversations",
    description=(
        "List all assistant conversations owned by the current user for "
        "this repository, most recently active first."
    ),
)
async def list_conversations(
    repository_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ConversationSummaryResponse]:
    """Return the current user's conversations for an owned repository."""
    repo = await RepositoryService.get_repository(db, current_user.id, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    conversations = await ConversationService.list_conversations(
        db, current_user.id, repository_id
    )
    return [ConversationSummaryResponse.model_validate(c) for c in conversations]


@router.get(
    "/{repository_id}/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a conversation with full message history",
    description="Retrieve one conversation and its messages in chronological order.",
)
async def get_conversation(
    repository_id: int,
    conversation_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationDetailResponse:
    """Return one conversation (with messages) if owned by the current user."""
    repo = await RepositoryService.get_repository(db, current_user.id, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    conversation = await ConversationService.get_owned_conversation(
        db, current_user.id, repository_id, conversation_id
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    return ConversationDetailResponse.model_validate(conversation)


@router.post(
    "/{repository_id}/explain",
    response_model=ExplainResponse,
    status_code=status.HTTP_200_OK,
    summary="Explain a file, line range, or symbol",
    description=(
        "Explain a specific part of an owned, indexed repository, grounded "
        "in retrieved evidence. Returns a defined insufficient-evidence "
        "result rather than a fabricated explanation when no sufficiently "
        "relevant indexed code is found for the target."
    ),
)
async def explain_code(
    repository_id: int,
    explain_request: ExplainRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm_provider: Annotated[BaseLLMProvider, Depends(get_llm_provider)],
    embedding_provider: Annotated[
        BaseEmbeddingProvider, Depends(get_embedding_provider)
    ],
) -> ExplainResponse:
    """Explain code, grounded in ``RAGService.search()`` evidence.

    Raises the same HTTP status mapping as ``/ask`` (see that endpoint's
    docstring) for repository/conversation ownership and LLM failures.
    """
    repo = await RepositoryService.get_repository(db, current_user.id, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    conversation = await _resolve_optional_conversation(
        db, current_user.id, repository_id, explain_request.conversation_id
    )
    settings = get_settings()
    history = (
        ConversationService.build_history(
            conversation, settings.LLM_MAX_HISTORY_MESSAGES
        )
        if conversation is not None
        else None
    )

    # Close out any transaction opened by the reads above BEFORE the slow
    # RAG retrieval / embedding / LLM calls below (see /ask for the same
    # pattern and rationale).
    if db.in_transaction():
        await db.commit()

    try:
        answer = await OrchestrationService.explain(
            db=db,
            repository_id=repo.id,
            owner_id=current_user.id,
            file_path=explain_request.file_path,
            start_line=explain_request.start_line,
            end_line=explain_request.end_line,
            symbol=explain_request.symbol,
            question=explain_request.question,
            llm_provider=llm_provider,
            embedding_provider=embedding_provider,
            token_budget=settings.LLM_CONTEXT_TOKEN_BUDGET,
            min_relevance_score=settings.LLM_MIN_RELEVANCE_SCORE,
            max_history_messages=settings.LLM_MAX_HISTORY_MESSAGES,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            history=history,
        )
    except (
        RepositoryNotIndexedError,
        LLMContextError,
        LLMTimeoutError,
        LLMRateLimitError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        _raise_for_llm_error(exc)
        raise  # unreachable; _raise_for_llm_error always raises

    if conversation is not None:
        await ConversationService.record_turn(
            db,
            conversation,
            user_content=(
                f"[explain] {explain_request.file_path}"
                + (
                    f":{explain_request.start_line}"
                    if explain_request.start_line
                    else ""
                )
            ),
            answer=answer,
        )

    return ExplainResponse(
        conversation_id=conversation.id if conversation is not None else None,
        status=answer.status,
        explanation=answer.answer,
        evidence=answer.evidence,
        model=answer.model,
        ingestion_id=answer.ingestion_id,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
    )


@router.post(
    "/{repository_id}/review",
    response_model=ReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Review repository code and/or user-provided code",
    description=(
        "Review code from an owned, indexed repository, and/or "
        "user-provided code/diff text (untrusted input, up to 20,000 "
        "characters), for a given focus area. Returns structured findings "
        "plus a human-readable summary. When the review is purely "
        "repository-scoped (no user_code) and no sufficiently relevant "
        "indexed code is found, returns a defined insufficient-evidence "
        "result rather than a fabricated review."
    ),
)
async def review_code(
    repository_id: int,
    review_request: ReviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm_provider: Annotated[BaseLLMProvider, Depends(get_llm_provider)],
    embedding_provider: Annotated[
        BaseEmbeddingProvider, Depends(get_embedding_provider)
    ],
) -> ReviewResponse:
    """Review code, grounded in ``RAGService.search()`` evidence where
    applicable, returning structured findings.

    Raises the same HTTP status mapping as ``/ask`` (see that endpoint's
    docstring) for repository/conversation ownership and LLM failures.
    """
    repo = await RepositoryService.get_repository(db, current_user.id, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    conversation = await _resolve_optional_conversation(
        db, current_user.id, repository_id, review_request.conversation_id
    )
    settings = get_settings()
    history = (
        ConversationService.build_history(
            conversation, settings.LLM_MAX_HISTORY_MESSAGES
        )
        if conversation is not None
        else None
    )

    # Close out any transaction opened by the reads above BEFORE the slow
    # RAG retrieval / embedding / LLM calls below (see /ask for the same
    # pattern and rationale).
    if db.in_transaction():
        await db.commit()

    try:
        review_answer = await OrchestrationService.review(
            db=db,
            repository_id=repo.id,
            owner_id=current_user.id,
            focus=review_request.focus.value,
            file_path=review_request.file_path,
            symbol=review_request.symbol,
            start_line=review_request.start_line,
            end_line=review_request.end_line,
            user_code=review_request.user_code,
            llm_provider=llm_provider,
            embedding_provider=embedding_provider,
            token_budget=settings.LLM_CONTEXT_TOKEN_BUDGET,
            min_relevance_score=settings.LLM_MIN_RELEVANCE_SCORE,
            max_history_messages=settings.LLM_MAX_HISTORY_MESSAGES,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            history=history,
        )
    except InvalidReviewTargetError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (
        RepositoryNotIndexedError,
        LLMContextError,
        LLMTimeoutError,
        LLMRateLimitError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        _raise_for_llm_error(exc)
        raise  # unreachable; _raise_for_llm_error always raises

    if conversation is not None:
        target_desc = review_request.file_path or "user-provided code"
        # Adapt the ReviewAnswer into the AssistantAnswer shape record_turn()
        # already knows how to persist -- no new persistence model needed.
        record_turn_answer = AssistantAnswer(
            status=review_answer.status,
            answer=review_answer.summary,
            evidence=review_answer.evidence,
            model=review_answer.model,
            ingestion_id=review_answer.ingestion_id,
            input_tokens=review_answer.input_tokens,
            output_tokens=review_answer.output_tokens,
        )
        await ConversationService.record_turn(
            db,
            conversation,
            user_content=f"[review:{review_request.focus.value}] {target_desc}",
            answer=record_turn_answer,
        )

    return ReviewResponse(
        conversation_id=conversation.id if conversation is not None else None,
        status=review_answer.status,
        summary=review_answer.summary,
        findings=[
            ReviewFindingResponse(
                title=f.title,
                severity=f.severity,
                category=f.category,
                explanation=f.explanation,
                recommendation=f.recommendation,
                file_path=f.file_path,
                start_line=f.start_line,
                end_line=f.end_line,
                evidence_chunk_ids=f.evidence_chunk_ids,
            )
            for f in review_answer.findings
        ],
        evidence=review_answer.evidence,
        model=review_answer.model,
        ingestion_id=review_answer.ingestion_id,
        input_tokens=review_answer.input_tokens,
        output_tokens=review_answer.output_tokens,
    )
