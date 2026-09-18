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


class TestVoyageTokenAwareBatchSplitting:
    """Pure unit tests for `_split_into_batches` -- no API calls."""

    def test_all_fit_in_one_batch_by_default(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        texts = [f"chunk {i}" for i in range(46)]
        batches = provider._split_into_batches(texts)
        assert batches == [texts]

    def test_splits_when_token_budget_exceeded(self) -> None:
        provider = VoyageEmbeddingProvider(
            api_key="pa-test", max_tokens_per_request=10, batch_size=1000
        )
        # Each ~20-char text estimates to int(20/3.5)+1 = 6 tokens; two of
        # them (12) exceed the 10-token budget, so each gets its own batch.
        texts = ["a" * 20, "b" * 20, "c" * 20]
        batches = provider._split_into_batches(texts)
        assert batches == [[texts[0]], [texts[1]], [texts[2]]]

    def test_respects_text_count_bound_even_under_token_budget(self) -> None:
        provider = VoyageEmbeddingProvider(
            api_key="pa-test", max_tokens_per_request=1_000_000, batch_size=2
        )
        texts = ["a", "b", "c"]
        batches = provider._split_into_batches(texts)
        assert batches == [["a", "b"], ["c"]]

    def test_preserves_order_across_batches(self) -> None:
        provider = VoyageEmbeddingProvider(
            api_key="pa-test", max_tokens_per_request=10, batch_size=1000
        )
        texts = [f"{c}" * 20 for c in "abcdef"]
        batches = provider._split_into_batches(texts)
        flattened = [t for batch in batches for t in batch]
        assert flattened == texts


class TestVoyageMultiBatchPacing:
    """Verifies pacing waits between multiple requests but never delays a
    single-request batch -- `asyncio.sleep` is mocked so these run instantly
    regardless of the configured requests-per-minute limit."""

    @pytest.mark.asyncio
    async def test_single_batch_incurs_no_pacing_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        mock_embed = AsyncMock(
            side_effect=lambda **kwargs: _fake_response(1024, len(kwargs["texts"]))
        )
        provider._client.embed = mock_embed  # type: ignore[method-assign]
        sleep_mock = AsyncMock()
        monkeypatch.setattr("app.rag.embeddings.voyage.asyncio.sleep", sleep_mock)

        result = await provider.embed_texts(["short chunk 1", "short chunk 2"])

        assert len(result) == 2
        assert mock_embed.call_count == 1
        sleep_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multi_batch_paces_between_requests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = VoyageEmbeddingProvider(
            api_key="pa-test",
            max_tokens_per_request=10,
            batch_size=1000,
            max_requests_per_minute=3,
        )
        mock_embed = AsyncMock(
            side_effect=lambda **kwargs: _fake_response(1024, len(kwargs["texts"]))
        )
        provider._client.embed = mock_embed  # type: ignore[method-assign]
        sleep_mock = AsyncMock()
        monkeypatch.setattr("app.rag.embeddings.voyage.asyncio.sleep", sleep_mock)

        # Each text alone exceeds the 10-token budget relative to the next,
        # forcing two separate batches/requests.
        result = await provider.embed_texts(["a" * 20, "b" * 20])

        assert len(result) == 2
        assert mock_embed.call_count == 2
        sleep_mock.assert_awaited_once()
        waited_seconds = sleep_mock.call_args.args[0]
        assert waited_seconds > 0
        # 60s / 3 requests-per-minute = 20s minimum spacing.
        assert waited_seconds == pytest.approx(20.0, abs=1.0)

    @pytest.mark.asyncio
    async def test_higher_requests_per_minute_limit_shortens_pacing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = VoyageEmbeddingProvider(
            api_key="pa-test",
            max_tokens_per_request=10,
            batch_size=1000,
            max_requests_per_minute=60,
        )
        mock_embed = AsyncMock(
            side_effect=lambda **kwargs: _fake_response(1024, len(kwargs["texts"]))
        )
        provider._client.embed = mock_embed  # type: ignore[method-assign]
        sleep_mock = AsyncMock()
        monkeypatch.setattr("app.rag.embeddings.voyage.asyncio.sleep", sleep_mock)

        await provider.embed_texts(["a" * 20, "b" * 20])

        sleep_mock.assert_awaited_once()
        waited_seconds = sleep_mock.call_args.args[0]
        # 60s / 60 requests-per-minute = 1s minimum spacing.
        assert waited_seconds == pytest.approx(1.0, abs=0.5)


class TestVoyageRetryConfigurationPreserved:
    """Requirement: preserve existing SDK-level retry/backoff for 429s --
    the AsyncClient's own `max_retries` must still be honored/forwarded."""

    def test_max_retries_and_timeout_forwarded_to_sdk_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        class FakeAsyncClient:
            def __init__(self, api_key: str, max_retries: int, timeout: float) -> None:
                captured["api_key"] = api_key
                captured["max_retries"] = max_retries
                captured["timeout"] = timeout

        monkeypatch.setattr("app.rag.embeddings.voyage.AsyncClient", FakeAsyncClient)

        VoyageEmbeddingProvider(api_key="pa-test", max_retries=7, timeout=12.0)

        assert captured["max_retries"] == 7
        assert captured["timeout"] == 12.0

    @pytest.mark.asyncio
    async def test_rate_limit_still_raises_typed_error_after_sdk_retries_exhausted(
        self,
    ) -> None:
        """The SDK itself owns the retry loop (voyageai.AsyncClient's own
        `max_retries`); once it's exhausted and still raises
        RateLimitError, this provider must still map that to
        EmbeddingRateLimitError -- unchanged by the pacing/splitting work
        above."""
        provider = VoyageEmbeddingProvider(api_key="pa-test")
        provider._client.embed = AsyncMock(  # type: ignore[method-assign]
            side_effect=voyage_error.RateLimitError("rate limited after retries")
        )
        with pytest.raises(EmbeddingRateLimitError):
            await provider.embed_query("q")


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
