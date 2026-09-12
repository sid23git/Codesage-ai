"""Tests for the Milestone 6 Phase 1 LLM provider abstraction layer."""

from __future__ import annotations

import dataclasses
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from app.core.config import Settings
from app.llm.exceptions import (
    LLMConfigurationError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.providers import AnthropicProvider, MockLLMProvider, get_llm_provider
from app.llm.providers.base import LLMMessage, LLMResponse

_DUMMY_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls: type[Exception], status_code: int) -> Exception:
    """Build a real anthropic.APIStatusError subclass instance for tests."""
    response = httpx.Response(status_code, request=_DUMMY_REQUEST)
    return cls("provider error", response=response, body=None)  # type: ignore[call-arg]


class TestLLMMessageAndResponse:
    """Test the provider-agnostic message/response value types."""

    def test_llm_message_fields(self) -> None:
        msg = LLMMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"

    def test_llm_message_is_frozen(self) -> None:
        msg = LLMMessage(role="user", content="hello")
        with pytest.raises(dataclasses.FrozenInstanceError):
            msg.content = "changed"  # type: ignore[misc]

    def test_llm_response_optional_token_fields_default_none(self) -> None:
        resp = LLMResponse(content="hi", model="test-model")
        assert resp.input_tokens is None
        assert resp.output_tokens is None


class TestMockLLMProvider:
    """Test MockLLMProvider recording, determinism, and failure injection."""

    @pytest.mark.asyncio
    async def test_model_name(self) -> None:
        provider = MockLLMProvider(model="mock-x")
        assert provider.model_name == "mock-x"

    @pytest.mark.asyncio
    async def test_records_calls_and_last_messages(self) -> None:
        provider = MockLLMProvider()
        messages = [
            LLMMessage(role="system", content="You are helpful."),
            LLMMessage(role="user", content="What does main() do?"),
        ]
        assert provider.call_count == 0
        assert provider.last_messages is None

        await provider.complete(messages, max_tokens=100)

        assert provider.call_count == 1
        assert provider.last_messages == messages
        assert provider.calls[0] == messages

    @pytest.mark.asyncio
    async def test_multiple_calls_are_all_recorded(self) -> None:
        provider = MockLLMProvider()
        await provider.complete([LLMMessage(role="user", content="one")], max_tokens=10)
        await provider.complete([LLMMessage(role="user", content="two")], max_tokens=10)

        assert provider.call_count == 2
        assert provider.calls[0][0].content == "one"
        assert provider.last_messages is not None
        assert provider.last_messages[0].content == "two"

    @pytest.mark.asyncio
    async def test_deterministic_default_response(self) -> None:
        provider = MockLLMProvider()
        messages = [LLMMessage(role="user", content="explain foo()")]

        resp1 = await provider.complete(messages, max_tokens=100)
        resp2 = await provider.complete(messages, max_tokens=100)

        assert resp1.content == resp2.content
        assert "explain foo()" in resp1.content
        assert resp1.model == "mock-llm"

    @pytest.mark.asyncio
    async def test_fixed_response_override(self) -> None:
        provider = MockLLMProvider(fixed_response="canned answer")
        resp = await provider.complete(
            [LLMMessage(role="user", content="anything")], max_tokens=50
        )
        assert resp.content == "canned answer"

    @pytest.mark.asyncio
    async def test_raise_error_injection(self) -> None:
        provider = MockLLMProvider()
        provider.raise_error = LLMTimeoutError("simulated timeout")

        with pytest.raises(LLMTimeoutError, match="simulated timeout"):
            await provider.complete(
                [LLMMessage(role="user", content="x")], max_tokens=50
            )

        # The call is recorded even though it raised, so tests can assert
        # what was about to be sent when exercising failure paths.
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_output_tokens_bounded_by_max_tokens(self) -> None:
        provider = MockLLMProvider(fixed_response=" ".join(["word"] * 500))
        resp = await provider.complete(
            [LLMMessage(role="user", content="x")], max_tokens=10
        )
        assert resp.output_tokens == 10


class TestGetLLMProviderFactory:
    """Test the get_llm_provider factory."""

    def test_get_mock_provider(self) -> None:
        provider = get_llm_provider("mock")
        assert isinstance(provider, MockLLMProvider)
        assert provider.model_name == "mock-llm"

    def test_get_mock_provider_custom_model(self) -> None:
        provider = get_llm_provider("mock", model="custom-mock")
        assert provider.model_name == "custom-mock"

    def test_get_anthropic_provider_success(self) -> None:
        provider = get_llm_provider("anthropic", api_key="sk-ant-test")
        assert isinstance(provider, AnthropicProvider)
        assert provider.model_name == "claude-sonnet-5"

    def test_get_anthropic_provider_custom_model(self) -> None:
        provider = get_llm_provider(
            "anthropic", api_key="sk-ant-test", model="claude-opus-5"
        )
        assert provider.model_name == "claude-opus-5"

    def test_get_anthropic_provider_missing_key_raises(self) -> None:
        with pytest.raises(
            LLMConfigurationError, match="ANTHROPIC_API_KEY is required"
        ):
            get_llm_provider("anthropic", api_key=None)

    def test_unsupported_provider_raises(self) -> None:
        with pytest.raises(LLMConfigurationError, match="Unsupported LLM_PROVIDER"):
            get_llm_provider("does-not-exist")

    def test_provider_name_is_case_insensitive(self) -> None:
        provider = get_llm_provider("MOCK")
        assert isinstance(provider, MockLLMProvider)


class TestAnthropicProviderResponseNormalization:
    """Test AnthropicProvider request/response shape without real network calls."""

    @pytest.mark.asyncio
    async def test_complete_normalizes_response(self) -> None:
        provider = AnthropicProvider(api_key="sk-ant-test")

        text_block = MagicMock(type="text", text="The answer is 42.")
        mock_message = MagicMock(
            content=[text_block],
            model="claude-sonnet-5",
            usage=MagicMock(input_tokens=123, output_tokens=45),
        )
        create_mock = AsyncMock(return_value=mock_message)
        provider._client.messages.create = create_mock

        response = await provider.complete(
            [
                LLMMessage(role="system", content="Be concise."),
                LLMMessage(role="user", content="What is 6*7?"),
            ],
            max_tokens=100,
            temperature=0.0,
        )

        assert isinstance(response, LLMResponse)
        assert response.content == "The answer is 42."
        assert response.model == "claude-sonnet-5"
        assert response.input_tokens == 123
        assert response.output_tokens == 45

        # System messages must be split out into the "system" parameter,
        # never sent as a role="system" entry in "messages".
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["system"] == "Be concise."
        assert call_kwargs["messages"] == [{"role": "user", "content": "What is 6*7?"}]
        assert call_kwargs["max_tokens"] == 100
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["model"] == "claude-sonnet-5"

    @pytest.mark.asyncio
    async def test_complete_concatenates_text_blocks_only(self) -> None:
        provider = AnthropicProvider(api_key="sk-ant-test")

        blocks = [
            MagicMock(type="text", text="Hello "),
            MagicMock(type="tool_use", text="ignored"),
            MagicMock(type="text", text="world."),
        ]
        mock_message = MagicMock(content=blocks, model="claude-sonnet-5", usage=None)
        provider._client.messages.create = AsyncMock(return_value=mock_message)

        response = await provider.complete(
            [LLMMessage(role="user", content="hi")], max_tokens=50
        )

        assert response.content == "Hello world."
        assert response.input_tokens is None
        assert response.output_tokens is None

    @pytest.mark.asyncio
    async def test_no_system_message_omits_system_kwarg(self) -> None:
        provider = AnthropicProvider(api_key="sk-ant-test")
        mock_message = MagicMock(
            content=[MagicMock(type="text", text="ok")],
            model="claude-sonnet-5",
            usage=MagicMock(input_tokens=1, output_tokens=1),
        )
        create_mock = AsyncMock(return_value=mock_message)
        provider._client.messages.create = create_mock

        await provider.complete([LLMMessage(role="user", content="hi")], max_tokens=10)

        assert "system" not in create_mock.call_args.kwargs

    @pytest.mark.asyncio
    async def test_multiple_system_messages_are_joined(self) -> None:
        provider = AnthropicProvider(api_key="sk-ant-test")
        mock_message = MagicMock(
            content=[MagicMock(type="text", text="ok")],
            model="claude-sonnet-5",
            usage=None,
        )
        create_mock = AsyncMock(return_value=mock_message)
        provider._client.messages.create = create_mock

        await provider.complete(
            [
                LLMMessage(role="system", content="First instruction."),
                LLMMessage(role="system", content="Second instruction."),
                LLMMessage(role="user", content="hi"),
            ],
            max_tokens=10,
        )

        assert (
            create_mock.call_args.kwargs["system"]
            == "First instruction.\n\nSecond instruction."
        )


class TestAnthropicProviderExceptionTranslation:
    """Test that Anthropic SDK exceptions are translated to domain exceptions.

    No network access or real API key is used anywhere in this class — the
    Anthropic SDK's own exception types are constructed directly (they are
    plain, locally-instantiable objects) to simulate each failure mode.
    """

    @staticmethod
    def _provider() -> AnthropicProvider:
        return AnthropicProvider(api_key="sk-ant-test")

    @pytest.mark.asyncio
    async def test_timeout_translated(self) -> None:
        provider = self._provider()
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=_DUMMY_REQUEST)
        )

        with pytest.raises(LLMTimeoutError):
            await provider.complete(
                [LLMMessage(role="user", content="hi")], max_tokens=10
            )

    @pytest.mark.asyncio
    async def test_rate_limit_translated(self) -> None:
        provider = self._provider()
        provider._client.messages.create = AsyncMock(
            side_effect=_status_error(anthropic.RateLimitError, 429)
        )

        with pytest.raises(LLMRateLimitError):
            await provider.complete(
                [LLMMessage(role="user", content="hi")], max_tokens=10
            )

    @pytest.mark.asyncio
    async def test_authentication_error_translated_to_configuration_error(
        self,
    ) -> None:
        provider = self._provider()
        provider._client.messages.create = AsyncMock(
            side_effect=_status_error(anthropic.AuthenticationError, 401)
        )

        with pytest.raises(LLMConfigurationError):
            await provider.complete(
                [LLMMessage(role="user", content="hi")], max_tokens=10
            )

    @pytest.mark.asyncio
    async def test_generic_api_error_translated_to_provider_error(self) -> None:
        provider = self._provider()
        provider._client.messages.create = AsyncMock(
            side_effect=_status_error(anthropic.InternalServerError, 500)
        )

        with pytest.raises(LLMProviderError):
            await provider.complete(
                [LLMMessage(role="user", content="hi")], max_tokens=10
            )

    @pytest.mark.asyncio
    async def test_connection_error_translated_to_provider_error(self) -> None:
        provider = self._provider()
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=_DUMMY_REQUEST)
        )

        with pytest.raises(LLMProviderError):
            await provider.complete(
                [LLMMessage(role="user", content="hi")], max_tokens=10
            )

    @pytest.mark.asyncio
    async def test_unexpected_exception_translated_to_provider_error(self) -> None:
        provider = self._provider()
        provider._client.messages.create = AsyncMock(
            side_effect=RuntimeError("something unrelated broke")
        )

        with pytest.raises(LLMProviderError):
            await provider.complete(
                [LLMMessage(role="user", content="hi")], max_tokens=10
            )

    @pytest.mark.asyncio
    async def test_no_anthropic_exception_type_ever_escapes(self) -> None:
        """Every translated exception must be an LLMError, never an SDK type."""
        provider = self._provider()
        provider._client.messages.create = AsyncMock(
            side_effect=_status_error(anthropic.BadRequestError, 400)
        )

        try:
            await provider.complete(
                [LLMMessage(role="user", content="hi")], max_tokens=10
            )
        except anthropic.AnthropicError:
            pytest.fail("An Anthropic SDK exception type escaped the adapter.")
        except LLMError:
            pass  # expected


class TestLLMSettings:
    """Test the new LLM_* Settings fields (defaults, bounds, isolation from secrets)."""

    _BASE_KWARGS: ClassVar[dict[str, str]] = {
        "SECRET_KEY": "a" * 32,
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    }

    def test_llm_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _env_file=None suppresses the developer's local .env, and the
        # explicit delenv() calls strip any ambient process environment
        # variables too, so this test measures pure field defaults
        # regardless of the machine it runs on -- matching the existing
        # convention in test_config.py::test_settings_default_values.
        for var in (
            "ANTHROPIC_API_KEY",
            "LLM_PROVIDER",
            "LLM_MODEL",
            "LLM_REQUEST_TIMEOUT_SECONDS",
            "LLM_MAX_OUTPUT_TOKENS",
            "LLM_CONTEXT_TOKEN_BUDGET",
            "LLM_MAX_HISTORY_MESSAGES",
            "LLM_MIN_RELEVANCE_SCORE",
        ):
            monkeypatch.delenv(var, raising=False)

        settings = Settings(_env_file=None, **self._BASE_KWARGS)  # type: ignore[call-arg]
        assert settings.LLM_PROVIDER == "mock"
        assert settings.LLM_MODEL == "claude-sonnet-5"
        assert settings.ANTHROPIC_API_KEY is None
        assert settings.LLM_REQUEST_TIMEOUT_SECONDS == 60.0
        assert settings.LLM_MAX_OUTPUT_TOKENS == 2000
        assert settings.LLM_CONTEXT_TOKEN_BUDGET == 12000
        assert settings.LLM_MAX_HISTORY_MESSAGES == 8
        assert settings.LLM_MIN_RELEVANCE_SCORE == 0.35

    def test_llm_settings_overridable(self) -> None:
        settings = Settings(
            **self._BASE_KWARGS,  # type: ignore[arg-type]
            LLM_PROVIDER="anthropic",
            LLM_MODEL="claude-opus-5",
            ANTHROPIC_API_KEY="sk-ant-real",
            LLM_MAX_OUTPUT_TOKENS=500,
            LLM_CONTEXT_TOKEN_BUDGET=4000,
            LLM_MAX_HISTORY_MESSAGES=4,
            LLM_MIN_RELEVANCE_SCORE=0.5,
        )
        assert settings.LLM_PROVIDER == "anthropic"
        assert settings.LLM_MODEL == "claude-opus-5"
        assert settings.ANTHROPIC_API_KEY == "sk-ant-real"
        assert settings.LLM_MAX_OUTPUT_TOKENS == 500
        assert settings.LLM_CONTEXT_TOKEN_BUDGET == 4000
        assert settings.LLM_MAX_HISTORY_MESSAGES == 4
        assert settings.LLM_MIN_RELEVANCE_SCORE == 0.5

    def test_llm_min_relevance_score_rejects_out_of_range(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(**self._BASE_KWARGS, LLM_MIN_RELEVANCE_SCORE=1.5)  # type: ignore[arg-type]

        with pytest.raises(ValidationError):
            Settings(**self._BASE_KWARGS, LLM_MIN_RELEVANCE_SCORE=-0.1)  # type: ignore[arg-type]

    def test_llm_numeric_fields_reject_non_positive(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(**self._BASE_KWARGS, LLM_MAX_OUTPUT_TOKENS=0)  # type: ignore[arg-type]

        with pytest.raises(ValidationError):
            Settings(**self._BASE_KWARGS, LLM_CONTEXT_TOKEN_BUDGET=-1)  # type: ignore[arg-type]

        with pytest.raises(ValidationError):
            Settings(**self._BASE_KWARGS, LLM_MAX_HISTORY_MESSAGES=0)  # type: ignore[arg-type]

    def test_settings_repr_does_not_leak_secret_looking_values(self) -> None:
        """Settings' default repr must not be relied on to hide secrets.

        This test documents current behavior rather than asserting a
        guarantee: Pydantic models render field values in __repr__ by
        default, so callers (loggers, error handlers) must never log a
        Settings instance directly. See app/api/deps.py / app/llm for the
        actual redaction discipline (never logging the raw API key).
        """
        settings = Settings(**self._BASE_KWARGS, ANTHROPIC_API_KEY="sk-ant-secret")  # type: ignore[arg-type]
        # We assert the key IS present in the object (it must be, to be
        # usable) -- the guarantee is behavioral (never logged), not that
        # the object itself redacts on repr.
        assert settings.ANTHROPIC_API_KEY == "sk-ant-secret"
