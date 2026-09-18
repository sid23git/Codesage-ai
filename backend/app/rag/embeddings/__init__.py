"""Embedding generation abstraction layer for RAG."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.exceptions import EmbeddingConfigurationError
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.rag.embeddings.openai import OpenAIEmbeddingProvider
from app.rag.embeddings.voyage import VoyageEmbeddingProvider

if TYPE_CHECKING:
    from app.core.config import Settings

_DEFAULT_VOYAGE_MODEL = "voyage-code-4"
_DEFAULT_VOYAGE_DIMENSION = 1024
_DEFAULT_MOCK_DIMENSION = 1024


def get_provider(
    name: str,
    api_key: str | None = None,
    model: str | None = None,
    dimension: int | None = None,
    timeout: float = 60.0,
    max_retries: int = 3,
    max_tokens_per_instance: int = 2_000_000,
    max_tokens_per_request: int = 8_000,
    max_requests_per_minute: int = 3,
) -> BaseEmbeddingProvider:
    """Factory method to get the configured embedding provider.

    Parameters
    ----------
    name:
        Provider identifier: ``"voyage"``, ``"openai"``, or ``"mock"``.
    api_key:
        Required for ``"voyage"`` and ``"openai"``; ignored for ``"mock"``.
    model:
        Model identifier. Falls back to each provider's own default when
        omitted (only meaningful for ``"voyage"``; ``"openai"`` and
        ``"mock"`` do not currently accept a caller-supplied model).
    dimension:
        Output vector dimension. Forwarded to ``"voyage"`` (default 1024)
        and ``"mock"`` (default 1024, so mock vectors always match whatever
        dimension the live schema expects); ``"openai"`` has a fixed,
        non-configurable dimension of its own.
    timeout:
        Per-request timeout in seconds (``"voyage"`` only).
    max_retries:
        Automatic SDK-level retries on transient failures (``"voyage"`` only).
    max_tokens_per_instance:
        Hard cap on embedding tokens this provider instance will spend
        before refusing further requests (``"voyage"`` only) -- see
        ``EmbeddingBudgetExceededError``.
    max_tokens_per_request:
        Maximum estimated tokens per individual embedding API request --
        larger text batches are split across multiple requests to stay
        under this (``"voyage"`` only).
    max_requests_per_minute:
        Consecutive requests from one provider instance are paced to stay
        at or under this many requests per minute when a batch must be
        split across multiple requests (``"voyage"`` only).

    Returns
    -------
    BaseEmbeddingProvider
        The configured provider instance.

    Raises
    ------
    EmbeddingConfigurationError
        If *name* is not a supported provider, or a required API key is
        missing for the selected provider.
    """
    normalized = name.lower()

    if normalized == "voyage":
        if not api_key:
            raise EmbeddingConfigurationError(
                "VOYAGE_API_KEY is required for the voyage embedding provider."
            )
        return VoyageEmbeddingProvider(
            api_key=api_key,
            model=model or _DEFAULT_VOYAGE_MODEL,
            dimension=dimension or _DEFAULT_VOYAGE_DIMENSION,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens_per_instance=max_tokens_per_instance,
            max_tokens_per_request=max_tokens_per_request,
            max_requests_per_minute=max_requests_per_minute,
        )

    if normalized == "openai":
        if not api_key:
            raise EmbeddingConfigurationError(
                "OPENAI_API_KEY is required for the openai embedding provider."
            )
        return OpenAIEmbeddingProvider(api_key=api_key)

    if normalized == "mock":
        return MockEmbeddingProvider(dimension=dimension or _DEFAULT_MOCK_DIMENSION)

    raise EmbeddingConfigurationError(
        f"Unsupported EMBEDDING_PROVIDER: {name!r}. "
        "Supported values: 'voyage', 'openai', 'mock'."
    )


def get_configured_embedding_provider(settings: Settings) -> BaseEmbeddingProvider:
    """Construct the embedding provider selected by ``settings.EMBEDDING_PROVIDER``.

    This is the single source of truth for "given a ``Settings`` object,
    which provider instance should be used" -- both
    ``app.api.deps.get_embedding_provider`` (the FastAPI dependency) and
    ``app.services.ingestion_service.IngestionService``'s internal fallback
    call this instead of calling ``get_provider`` directly with their own
    hand-picked arguments, so the two call sites can never drift out of
    sync (e.g. one of them passing ``OPENAI_API_KEY`` when
    ``EMBEDDING_PROVIDER=voyage`` is actually configured).
    """
    api_key = (
        settings.VOYAGE_API_KEY
        if settings.EMBEDDING_PROVIDER.lower() == "voyage"
        else settings.OPENAI_API_KEY
    )
    return get_provider(
        name=settings.EMBEDDING_PROVIDER,
        api_key=api_key,
        model=settings.EMBEDDING_MODEL,
        dimension=settings.EMBEDDING_DIMENSIONS,
        timeout=settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS,
        max_retries=settings.EMBEDDING_MAX_RETRIES,
        max_tokens_per_instance=settings.EMBEDDING_MAX_TOKENS_PER_INGESTION,
        max_tokens_per_request=settings.EMBEDDING_MAX_TOKENS_PER_REQUEST,
        max_requests_per_minute=settings.EMBEDDING_MAX_REQUESTS_PER_MINUTE,
    )


__all__ = [
    "BaseEmbeddingProvider",
    "EmbeddingConfigurationError",
    "MockEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "VoyageEmbeddingProvider",
    "get_configured_embedding_provider",
    "get_provider",
]
