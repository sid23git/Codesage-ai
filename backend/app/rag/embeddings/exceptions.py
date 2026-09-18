"""Provider-agnostic embedding exceptions.

Every concrete embedding provider adapter (``app/rag/embeddings/*``) must
catch its own SDK-specific exceptions and re-raise one of these. No provider
SDK exception type may cross that boundary -- callers (``RAGService``,
``IngestionService``, the ``get_embedding_provider`` dependency) only ever
need to know about this hierarchy, mirroring ``app/llm/exceptions.py``.
"""

from __future__ import annotations


class EmbeddingError(Exception):
    """Base class for all provider-agnostic embedding errors."""


class EmbeddingTimeoutError(EmbeddingError):
    """The provider did not respond within the configured timeout."""


class EmbeddingRateLimitError(EmbeddingError):
    """The provider rejected the request due to rate limiting."""


class EmbeddingProviderError(EmbeddingError):
    """The provider returned an unexpected failure (5xx, network error, etc.)."""


class EmbeddingConfigurationError(EmbeddingError):
    """The embedding provider/configuration itself is invalid.

    Raised for both setup-time problems (unsupported ``EMBEDDING_PROVIDER``
    name, missing API key) and request-time credential rejection (the
    provider reports the configured API key is invalid).
    """


class EmbeddingDimensionError(EmbeddingError):
    """A provider returned a vector whose length does not match the
    configured/expected dimension.

    This is a hard integrity failure: an embedding of the wrong dimension
    cannot be inserted into the ``code_chunks.embedding`` pgvector column
    (which is fixed-width) and must never be silently truncated or padded.
    """


class EmbeddingBudgetExceededError(EmbeddingError):
    """The configured token-spend guard would be (or was) exceeded.

    Raised fail-closed, before the request that would cross the budget is
    sent -- never after the fact. Protects a small production deployment
    from a runaway or misconfigured ingestion burning unexpected embedding
    provider spend.
    """
