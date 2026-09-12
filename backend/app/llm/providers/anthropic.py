"""Anthropic provider adapter.

Isolates the ``anthropic`` SDK behind ``BaseLLMProvider``. No Anthropic SDK
type (client, message, exception) is ever returned or raised across this
module's boundary — callers only ever see ``LLMResponse`` or one of the
``app.llm.exceptions.LLMError`` subclasses, mirroring how
``app.rag.embeddings.openai.OpenAIEmbeddingProvider`` isolates the
``openai`` SDK for M5.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.llm.exceptions import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.providers.base import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider(BaseLLMProvider):
    """Generates completions using the Anthropic Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResponse:
        # The Anthropic Messages API takes "system" as a separate top-level
        # parameter rather than a message with role="system" -- split
        # accordingly before calling the SDK.
        system_parts = [m.content for m in messages if m.role == "system"]
        chat_messages: list[dict[str, str]] = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat_messages,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            logger.warning("Anthropic request timed out.")
            raise LLMTimeoutError("Anthropic request timed out.") from exc
        except anthropic.RateLimitError as exc:
            logger.warning("Anthropic rate limit exceeded.")
            raise LLMRateLimitError("Anthropic rate limit exceeded.") from exc
        except anthropic.AuthenticationError as exc:
            logger.warning("Anthropic rejected the configured API key.")
            raise LLMConfigurationError(
                "Anthropic rejected the configured API key."
            ) from exc
        except anthropic.APIError as exc:
            logger.warning("Anthropic API request failed: %s", type(exc).__name__)
            raise LLMProviderError(
                f"Anthropic API request failed ({type(exc).__name__})."
            ) from exc
        except Exception as exc:
            logger.error("Unexpected error calling Anthropic: %s", type(exc).__name__)
            raise LLMProviderError(
                f"Unexpected error calling Anthropic ({type(exc).__name__})."
            ) from exc

        content = "".join(
            block.text for block in response.content if block.type == "text"
        )
        usage = response.usage

        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
        )
