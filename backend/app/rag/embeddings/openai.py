"""OpenAI embedding provider."""

import logging

import tiktoken
from openai import AsyncOpenAI

from app.rag.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings using OpenAI API."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        batch_size: int = 64,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._batch_size = batch_size
        self._encoder = tiktoken.encoding_for_model(model)

        # text-embedding-3-small and ada-002 use 1536 dimensions natively
        self._dimension = 1536

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    def _truncate(self, text: str, max_tokens: int = 8191) -> str:
        """Truncate text to the max token limit for the embedding model."""
        tokens = self._encoder.encode(text)
        if len(tokens) > max_tokens:
            logger.warning(
                "Truncating text from %d to %d tokens.", len(tokens), max_tokens
            )
            return self._encoder.decode(tokens[:max_tokens])
        return text

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]

            # Truncate to avoid API token limits (8191 tokens for text-embedding-3)
            safe_batch = [self._truncate(text) for text in batch]

            try:
                response = await self._client.embeddings.create(
                    input=safe_batch, model=self._model
                )

                # Extract embeddings in the correct order
                batch_embeddings = [None] * len(batch)
                for data in response.data:
                    batch_embeddings[data.index] = data.embedding  # type: ignore

                all_embeddings.extend(batch_embeddings)  # type: ignore

            except Exception as exc:
                logger.error(f"OpenAI embedding batch failed: {exc}")
                raise RuntimeError(f"Failed to generate embeddings: {exc}") from exc

        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        results = await self.embed_texts([query])
        return results[0]
