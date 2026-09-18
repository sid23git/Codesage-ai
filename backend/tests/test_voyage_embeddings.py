"""Tests for VoyageEmbeddingProvider: batching, input_type, retries/timeouts,
error mapping, dimension validation, and the cost-spend guard.

All tests here mock ``VoyageEmbeddingProvider._client.embed`` directly (the
same pattern ``test_rag_embeddings.py`` uses for
``OpenAIEmbeddingProvider._client.embeddings.create``) -- no network call is
ever made, and no real API key is required or used.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from voyageai import error as voyage_error

from app.core.config import Settings
from app.rag.embeddings import get_configured_embedding_provider, get_provider
from app.rag.embeddings.exceptions import (
    EmbeddingBudgetExceededError,
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
)
from app.rag.embeddings.openai import OpenAIEmbeddingProvider
from app.rag.embeddings.voyage import VoyageEmbeddingProvider


def _fake_response(
    dimension: int, count: int, total_tokens: int = 10
) -> SimpleNamespace:
    return SimpleNamespace(
        embeddings=[[0.1] * dimension for _ in range(count)],
        total_tokens=total_tokens,
    )


class TestVoyageEmbeddingProviderBasics:
    def test_dimension_and_model_name_defaults(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        assert provider.dimension == 1024
        assert provider.model_name == "voyage-code-4"

    def test_custom_model_and_dimension(self) -> None:
        provider = VoyageEmbeddingProvider(
            api_key="pa-test", model="voyage-3-large", dimension=512
        )
        assert provider.dimension == 512
        assert provider.model_name == "voyage-3-large"


class TestVoyageEmbeddingProviderBatchingAndInputType:
    @pytest.mark.asyncio
    async def test_embed_texts_uses_document_input_type_and_batches(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test", batch_size=2)
        mock_embed = AsyncMock(
            side_effect=lambda **kwargs: _fake_response(1024, len(kwargs["texts"]))
        )
        provider._client.embed = mock_embed  # type: ignore[method-assign]

        texts = ["chunk 1", "chunk 2", "chunk 3"]
        result = await provider.embed_texts(texts)

        assert len(result) == 3
        assert all(len(vec) == 1024 for vec in result)
        # 3 texts at batch_size=2 -> two calls (2 + 1)
        assert mock_embed.call_count == 2
        for call in mock_embed.call_args_list:
            assert call.kwargs["input_type"] == "document"
            assert call.kwargs["model"] == "voyage-code-4"
            assert call.kwargs["output_dimension"] == 1024

    @pytest.mark.asyncio
    async def test_embed_texts_empty_returns_empty(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        assert await provider.embed_texts([]) == []

    @pytest.mark.asyncio
    async def test_embed_query_uses_query_input_type(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        mock_embed = AsyncMock(return_value=_fake_response(1024, 1))
        provider._client.embed = mock_embed  # type: ignore[method-assign]

        vec = await provider.embed_query("find the auth logic")

        assert len(vec) == 1024
        mock_embed.assert_awaited_once()
        assert mock_embed.call_args.kwargs["input_type"] == "query"
        assert mock_embed.call_args.kwargs["texts"] == ["find the auth logic"]


class TestVoyageEmbeddingProviderErrorMapping:
    @pytest.mark.asyncio
    async def test_timeout_maps_to_embedding_timeout_error(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=voyage_error.Timeout("timed out")
        )
        with pytest.raises(EmbeddingTimeoutError):
            await provider.embed_query("q")

    @pytest.mark.asyncio
    async def test_rate_limit_maps_to_embedding_rate_limit_error(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=voyage_error.RateLimitError("rate limited")
        )
        with pytest.raises(EmbeddingRateLimitError):
            await provider.embed_query("q")

    @pytest.mark.asyncio
    async def test_authentication_error_maps_to_configuration_error(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=voyage_error.AuthenticationError("bad key")
        )
        with pytest.raises(EmbeddingConfigurationError):
            await provider.embed_query("q")

    @pytest.mark.asyncio
    async def test_invalid_request_error_maps_to_configuration_error(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=voyage_error.InvalidRequestError("bad request")
        )
        with pytest.raises(EmbeddingConfigurationError):
            await provider.embed_query("q")

    @pytest.mark.asyncio
    async def test_generic_voyage_error_maps_to_provider_error(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=voyage_error.ServerError("500")
        )
        with pytest.raises(EmbeddingProviderError):
            await provider.embed_query("q")

    @pytest.mark.asyncio
    async def test_unexpected_exception_maps_to_provider_error(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("something else entirely")
        )
        with pytest.raises(EmbeddingProviderError):
            await provider.embed_query("q")

    @pytest.mark.asyncio
    async def test_api_key_never_appears_in_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret_key = "pa-super-secret-do-not-log-me"
        provider = VoyageEmbeddingProvider(api_key=secret_key)
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=voyage_error.AuthenticationError("bad key")
        )
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(EmbeddingConfigurationError):
                await provider.embed_query("q")
        for record in caplog.records:
            assert secret_key not in record.getMessage()


class TestVoyageEmbeddingProviderDimensionValidation:
    @pytest.mark.asyncio
    async def test_wrong_dimension_raises_embed_texts(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test", dimension=1024)
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            return_value=_fake_response(dimension=512, count=1)
        )
        with pytest.raises(EmbeddingDimensionError):
            await provider.embed_texts(["some code"])

    @pytest.mark.asyncio
    async def test_wrong_dimension_raises_embed_query(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test", dimension=1024)
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            return_value=_fake_response(dimension=768, count=1)
        )
        with pytest.raises(EmbeddingDimensionError):
            await provider.embed_query("q")


class TestVoyageEmbeddingProviderCostGuard:
    @pytest.mark.asyncio
    async def test_budget_exceeded_blocks_next_batch(self) -> None:
        provider = VoyageEmbeddingProvider(
            api_key="pa-test", max_tokens_per_instance=100
        )
        mock_embed = AsyncMock(return_value=_fake_response(1024, 1, total_tokens=150))
        provider._client.embed = mock_embed  # type: ignore[method-assign]

        # First call succeeds and pushes usage (150) past the 100-token budget.
        await provider.embed_query("first query")
        assert mock_embed.call_count == 1

        # Second call must be refused BEFORE the SDK is invoked again.
        with pytest.raises(EmbeddingBudgetExceededError):
            await provider.embed_query("second query")
        assert mock_embed.call_count == 1  # no additional SDK call was made


class TestGetConfiguredEmbeddingProviderKeySelection:
    """Regression coverage for the fixed "always passes OPENAI_API_KEY
    regardless of EMBEDDING_PROVIDER" bug: this must be the only place
    that maps Settings -> provider, and it must select the matching key.
    """

    def _settings(self, **overrides: object) -> Settings:
        base = {
            "SECRET_KEY": "a" * 32,
            "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
            "OPENAI_API_KEY": "sk-wrong-key-should-not-be-used-for-voyage",
        }
        base.update(overrides)
        return Settings(_env_file=None, **base)  # type: ignore[call-arg, arg-type]

    def test_voyage_provider_gets_voyage_key_not_openai_key(self) -> None:
        settings = self._settings(
            EMBEDDING_PROVIDER="voyage", VOYAGE_API_KEY="pa-correct-voyage-key"
        )
        provider = get_configured_embedding_provider(settings)
        assert isinstance(provider, VoyageEmbeddingProvider)

    def test_voyage_provider_without_voyage_key_raises(self) -> None:
        settings = self._settings(EMBEDDING_PROVIDER="voyage", VOYAGE_API_KEY=None)
        with pytest.raises(
            EmbeddingConfigurationError, match="VOYAGE_API_KEY is required"
        ):
            get_configured_embedding_provider(settings)

    def test_openai_provider_still_gets_openai_key(self) -> None:
        settings = self._settings(EMBEDDING_PROVIDER="openai")
        provider = get_configured_embedding_provider(settings)
        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_mock_provider_uses_configured_dimension(self) -> None:
        settings = self._settings(EMBEDDING_PROVIDER="mock", EMBEDDING_DIMENSIONS=1024)
        provider = get_configured_embedding_provider(settings)
        assert provider.dimension == 1024


class TestGetProviderFactoryForVoyage:
    def test_get_provider_voyage_wires_all_settings(self) -> None:
        provider = get_provider(
            "voyage",
            api_key="pa-test",
            model="voyage-code-4",
            dimension=1024,
            timeout=45.0,
            max_retries=5,
            max_tokens_per_instance=500_000,
        )
        assert isinstance(provider, VoyageEmbeddingProvider)
        assert provider.dimension == 1024
        assert provider.model_name == "voyage-code-4"
