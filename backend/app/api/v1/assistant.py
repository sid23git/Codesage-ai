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
from app.services.conversation_service import ConversationService
from app.services.orchestration_service import (
    OrchestrationService,
    RepositoryNotIndexedError,
)
from app.services.repository_service import RepositoryService

router = APIRouter(prefix="/repositories", tags=["assistant"])


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
