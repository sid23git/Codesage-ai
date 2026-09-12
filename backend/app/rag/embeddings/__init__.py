"""Embedding generation abstraction layer for RAG."""

from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.rag.embeddings.openai import OpenAIEmbeddingProvider


def get_provider(name: str, api_key: str | None = None) -> BaseEmbeddingProvider:
    """Factory method to get the configured embedding provider."""
    if name.lower() == "openai":
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required for the openai embedding provider."
            )
        return OpenAIEmbeddingProvider(api_key=api_key)

    # Default to mock for tests and local dev
    return MockEmbeddingProvider()


__all__ = [
    "BaseEmbeddingProvider",
    "MockEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_provider",
]
