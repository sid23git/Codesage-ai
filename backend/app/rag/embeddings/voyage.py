"""Voyage AI embedding provider.

Isolates the ``voyageai`` SDK behind ``BaseEmbeddingProvider``. No Voyage SDK
type (client, response object, exception) is ever returned or raised across
this module's boundary -- callers only ever see a plain ``list[list[float]]``/
``list[float]`` or one of the ``app.rag.embeddings.exceptions.EmbeddingError``
subclasses, mirroring how ``app.llm.providers.anthropic.AnthropicProvider``
isolates the ``anthropic`` SDK.

Voyage's own SDK already retries transient failures internally (the
``max_retries`` constructor argument), so no hand-rolled backoff loop is
needed for 429s -- this module's job is timeout/retry *configuration*, SDK
exception -> typed exception mapping, dimension validation, the
per-instance token-spend guard, and (below) token-aware batch splitting plus
inter-request pacing so a free-tier/no-payment-method account's low
requests-per-minute and tokens-per-minute ceilings are respected proactively,
rather than relied upon to reject an oversized request after the fact.
"""

from __future__ import annotations

import asyncio
import logging
import time

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
# OR 120,000 tokens, whichever is hit first -- this is a secondary,
# text-count-based safety bound retained alongside the token-aware splitting
# below; in practice the token budget below is reached first for any
# account on a constrained (e.g. free/no-payment-method) tier.
_DEFAULT_BATCH_SIZE = 128
# Conservative default well under the ~10,000 tokens/minute ceiling observed
# on a free-tier Voyage account with no payment method on file (see
# docs.voyageai.com/docs/rate-limits) -- deliberately configurable via
# EMBEDDING_MAX_TOKENS_PER_REQUEST so an account with a payment method /
# higher tier can raise it without a code change.
_DEFAULT_MAX_TOKENS_PER_REQUEST = 8_000
# Matches the observed free-tier requests-per-minute ceiling. Configurable
# via EMBEDDING_MAX_REQUESTS_PER_MINUTE for the same reason.
_DEFAULT_MAX_REQUESTS_PER_MINUTE = 3
# Approximate characters-per-token for source code (denser in punctuation/
# identifiers than English prose, so this runs a little more conservative
# than the ~4 chars/token often quoted for prose). This is a local, offline
# heuristic used only to decide where to split a batch -- not a substitute
# for Voyage's own tokenizer and not used for billing. Deliberately NOT
# using voyageai.AsyncClient.count_tokens() here: that call downloads and
# runs the real per-model HuggingFace tokenizer on first use, which would
# add an external network dependency (to huggingface.co) and latency to the
# ingestion hot path merely to compute a splitting heuristic that only
# needs to be approximately conservative, not exact.
_CHARS_PER_TOKEN_ESTIMATE = 3.5


class VoyageEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings using the Voyage AI API (``voyage-code-4`` by default).

    Batches are split to stay under both a maximum text count
    (``batch_size``) and a maximum estimated token count
    (``max_tokens_per_request``) per API call, and consecutive calls from
    one instance are paced to stay under ``max_requests_per_minute`` --
    together these keep a single ingestion run within a constrained
    (e.g. free-tier, no-payment-method) Voyage account's limits without
    ever needing to add a payment method, while adding zero artificial
    delay for a single-batch request or an account on a higher tier.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        dimension: int = _DEFAULT_DIMENSION,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        timeout: float = 60.0,
        max_retries: int = 3,
        max_tokens_per_instance: int = 2_000_000,
        max_tokens_per_request: int = _DEFAULT_MAX_TOKENS_PER_REQUEST,
        max_requests_per_minute: int = _DEFAULT_MAX_REQUESTS_PER_MINUTE,
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
        self._max_tokens_per_request = max_tokens_per_request
        self._min_request_interval = 60.0 / max_requests_per_minute
        self._last_request_started_at: float | None = None

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed code chunk texts for indexing (``input_type="document"``).

        Splits *texts* into token-aware, count-bounded batches (see
        ``_split_into_batches``) and paces the resulting requests via
        ``_embed_batch`` -- a single small ingestion (everything fits in one
        batch) issues exactly one request with no artificial delay; a large
        ingestion spans multiple paced requests instead of one oversized one.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for batch in self._split_into_batches(texts):
            all_embeddings.extend(await self._embed_batch(batch, input_type="document"))
        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single search query (``input_type="query"``)."""
        results = await self._embed_batch([query], input_type="query")
        return results[0]

    def _estimate_tokens(self, text: str) -> int:
        """Conservative, offline token-count estimate -- see module docstring."""
        return max(1, int(len(text) / _CHARS_PER_TOKEN_ESTIMATE) + 1)

    def _split_into_batches(self, texts: list[str]) -> list[list[str]]:
        """Greedily pack *texts* into batches, each bounded by both
        ``self._batch_size`` (text count) and ``self._max_tokens_per_request``
        (estimated tokens), preserving input order so results still line up
        1:1 with the caller's original list once every batch is concatenated.

        A single text whose own estimated size already exceeds
        ``max_tokens_per_request`` is still emitted alone in its own batch
        (there is nothing smaller to split it into at this layer) -- Voyage
        itself will accept or reject it based on the real token count.
        """
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_tokens = 0

        for text in texts:
            text_tokens = self._estimate_tokens(text)
            would_exceed_tokens = (
                current_tokens + text_tokens > self._max_tokens_per_request
            )
            would_exceed_count = len(current_batch) >= self._batch_size
            if current_batch and (would_exceed_tokens or would_exceed_count):
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            current_batch.append(text)
            current_tokens += text_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    async def _pace_request(self) -> None:
        """Sleep as needed so this instance never issues requests faster
        than ``max_requests_per_minute`` -- a no-op for the first request,
        and a no-op whenever the previous request was already long enough
        ago, so an account on a higher tier (or a single-batch ingestion)
        never waits artificially."""
        if self._last_request_started_at is not None:
            elapsed = time.monotonic() - self._last_request_started_at
            remaining = self._min_request_interval - elapsed
            if remaining > 0:
                logger.info(
                    "Pacing Voyage request: waiting %.1fs to stay within "
                    "the configured requests-per-minute limit.",
                    remaining,
                )
                await asyncio.sleep(remaining)
        self._last_request_started_at = time.monotonic()

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

        await self._pace_request()

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
