"""Voyage AI embedding provider.

Isolates the ``voyageai`` SDK behind ``BaseEmbeddingProvider``. No Voyage SDK
type (client, response object, exception) is ever returned or raised across
this module's boundary -- callers only ever see a plain ``list[list[float]]``/
``list[float]`` or one of the ``app.rag.embeddings.exceptions.EmbeddingError``
subclasses, mirroring how ``app.llm.providers.anthropic.AnthropicProvider``
isolates the ``anthropic`` SDK.

Voyage's own SDK already retries transient failures internally (the
``max_retries`` constructor argument), so no hand-rolled backoff loop is
needed here -- this module's job is timeout/retry *configuration*, SDK
exception -> typed exception mapping, dimension validation, and the
per-instance token-spend guard.
"""

from __future__ import annotations

import logging

from voyageai import error as voyage_error
from voyageai.client_async import AsyncClient

from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.exceptions import (
    EmbeddingBudgetExceededError,
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "voyage-code-4"
_DEFAULT_DIMENSION = 1024
# Voyage's documented per-request ceiling for voyage-code-4 is 1,000 texts
# OR 120,000 tokens, whichever is hit first. Code chunks can individually be
# large, so this batch size stays well under the text-count ceiling as a
# safety margin against the token ceiling being hit first -- this is an
# internal safety default, not a documented Voyage limit itself. It is
# independent of (and nests inside) RAGService's own outer
# `_EMBEDDING_BATCH_SIZE = 64` loop: a 64-chunk outer batch simply becomes
# one Voyage API call here.
_DEFAULT_BATCH_SIZE = 128


class VoyageEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings using the Voyage AI API (``voyage-code-4`` by default)."""

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        dimension: int = _DEFAULT_DIMENSION,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        timeout: float = 60.0,
        max_retries: int = 3,
        max_tokens_per_instance: int = 2_000_000,
    ) -> None:
        # `api_key` is passed straight into the SDK client and never stored,
        # logged, or otherwise referenced again in this class -- it is not
        # retrievable from a VoyageEmbeddingProvider instance.
        self._client = AsyncClient(
            api_key=api_key, max_retries=max_retries, timeout=timeout
        )
        self._model = model
        self._dimension = dimension
        self._batch_size = batch_size
        self._max_tokens_per_instance = max_tokens_per_instance
        self._tokens_used = 0

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed code chunk texts for indexing (``input_type="document"``)."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            all_embeddings.extend(await self._embed_batch(batch, input_type="document"))
        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single search query (``input_type="query"``)."""
        results = await self._embed_batch([query], input_type="query")
        return results[0]

    async def _embed_batch(
        self, texts: list[str], input_type: str
    ) -> list[list[float]]:
        # Fail closed *before* spending further: once this instance has
        # already used up its budget (from a prior batch in the same
        # ingestion run), refuse to issue another request at all.
        if self._tokens_used >= self._max_tokens_per_instance:
            raise EmbeddingBudgetExceededError(
                f"Embedding token budget exceeded: {self._tokens_used} tokens "
                f"already used against a limit of {self._max_tokens_per_instance} "
                "for this ingestion run."
            )

        try:
            response = await self._client.embed(
                texts=texts,
                model=self._model,
                input_type=input_type,
                output_dimension=self._dimension,
            )
        except voyage_error.Timeout as exc:
            logger.warning("Voyage request timed out.")
            raise EmbeddingTimeoutError("Voyage request timed out.") from exc
        except voyage_error.RateLimitError as exc:
            logger.warning("Voyage rate limit exceeded.")
            raise EmbeddingRateLimitError("Voyage rate limit exceeded.") from exc
        except voyage_error.AuthenticationError as exc:
            logger.warning("Voyage rejected the configured API key.")
            raise EmbeddingConfigurationError(
                "Voyage rejected the configured API key."
            ) from exc
        except (
            voyage_error.InvalidRequestError,
            voyage_error.MalformedRequestError,
        ) as exc:
            logger.warning("Voyage rejected the request: %s", type(exc).__name__)
            raise EmbeddingConfigurationError(
                f"Voyage rejected the request ({type(exc).__name__})."
            ) from exc
        except voyage_error.VoyageError as exc:
            logger.warning("Voyage API request failed: %s", type(exc).__name__)
            raise EmbeddingProviderError(
                f"Voyage API request failed ({type(exc).__name__})."
            ) from exc
        except Exception as exc:
            logger.error("Unexpected error calling Voyage: %s", type(exc).__name__)
            raise EmbeddingProviderError(
                f"Unexpected error calling Voyage ({type(exc).__name__})."
            ) from exc

        self._tokens_used += response.total_tokens

        embeddings: list[list[float]] = [
            [float(x) for x in vector] for vector in response.embeddings
        ]
        for vector in embeddings:
            if len(vector) != self._dimension:
                raise EmbeddingDimensionError(
                    f"Voyage returned a {len(vector)}-dimensional vector; "
                    f"expected {self._dimension} (model={self._model})."
                )

        return embeddings
