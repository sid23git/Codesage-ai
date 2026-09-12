"""Tests for embedding provider abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.rag.embeddings import (
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_provider,
)


class TestMockEmbeddingProvider:
    """Test MockEmbeddingProvider behavior and determinism."""

    @pytest.mark.asyncio
    async def test_dimensions_and_model_name(self) -> None:
        provider = MockEmbeddingProvider()
        assert provider.dimension == 1536
        assert provider.model_name == "mock-deterministic-1536"

    @pytest.mark.asyncio
    async def test_embed_texts_deterministic(self) -> None:
        provider = MockEmbeddingProvider()
        texts = ["def calculate_total():", "class DatabaseConnection:"]

        vecs1 = await provider.embed_texts(texts)
        vecs2 = await provider.embed_texts(texts)

        assert len(vecs1) == 2
        assert len(vecs1[0]) == 1536
        assert len(vecs1[1]) == 1536
        assert vecs1[0] == vecs2[0]
        assert vecs1[1] == vecs2[1]
        assert vecs1[0] != vecs1[1]

    @pytest.mark.asyncio
    async def test_embed_query_matches_embed_texts(self) -> None:
        provider = MockEmbeddingProvider()
        query = "find authentication token"

        query_vec = await provider.embed_query(query)
        batch_vec = (await provider.embed_texts([query]))[0]

        assert query_vec == batch_vec

    @pytest.mark.asyncio
    async def test_unit_normalization(self) -> None:
        provider = MockEmbeddingProvider()
        vec = await provider.embed_query("some arbitrary code snippet")
        norm = sum(v * v for v in vec) ** 0.5
        assert pytest.approx(norm, rel=1e-5) == 1.0


class TestOpenAIEmbeddingProvider:
    """Test OpenAIEmbeddingProvider batching and truncation."""

    @pytest.mark.asyncio
    async def test_embed_texts_batches_and_truncates(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key", batch_size=2)
        assert provider.dimension == 1536
        assert provider.model_name == "text-embedding-3-small"

        mock_data_1 = MagicMock(index=0, embedding=[0.1] * 1536)
        mock_data_2 = MagicMock(index=1, embedding=[0.2] * 1536)
        mock_response = MagicMock(data=[mock_data_1, mock_data_2])

        mock_create = AsyncMock(return_value=mock_response)
        provider._client.embeddings.create = mock_create

        texts = ["chunk 1", "chunk 2", "chunk 3", "chunk 4"]
        embeddings = await provider.embed_texts(texts)

        assert len(embeddings) == 4
        assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_embed_texts_empty_returns_empty(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key")
        result = await provider.embed_texts([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_texts_error_raises_runtime_error(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="test-key")
        provider._client.embeddings.create = AsyncMock(
            side_effect=Exception("API Error")
        )

        with pytest.raises(RuntimeError, match="Failed to generate embeddings"):
            await provider.embed_texts(["some text"])


class TestGetProviderFactory:
    """Test get_provider factory."""

    def test_get_mock_provider(self) -> None:
        provider = get_provider("mock")
        assert isinstance(provider, MockEmbeddingProvider)

    def test_get_openai_provider_success(self) -> None:
        provider = get_provider("openai", api_key="sk-test")
        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_get_openai_provider_missing_key_raises(self) -> None:
        with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
            get_provider("openai", api_key=None)
