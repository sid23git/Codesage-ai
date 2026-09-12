"""Base embedding provider interface."""

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """Abstract interface for dense vector embedding generation."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Fixed embedding vector dimension (1536 for MVP)."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Canonical model identifier."""
        pass

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch generate embeddings for chunk text payloads."""
        pass

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding vector for a search query string."""
        pass
