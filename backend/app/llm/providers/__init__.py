"""LLM provider abstraction layer."""

from __future__ import annotations

from app.llm.exceptions import LLMConfigurationError
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.base import BaseLLMProvider, LLMMessage, LLMResponse
from app.llm.providers.mock import MockLLMProvider

_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
_DEFAULT_MOCK_MODEL = "mock-llm"


def get_llm_provider(
    name: str,
    api_key: str | None = None,
    model: str | None = None,
    timeout: float = 60.0,
) -> BaseLLMProvider:
    """Factory method to get the configured LLM provider.

    Parameters
    ----------
    name:
        Provider identifier: ``"anthropic"`` or ``"mock"``.
    api_key:
        Required for ``"anthropic"``; ignored for ``"mock"``.
    model:
        Model identifier to use. Falls back to each provider's own default
        when omitted.
    timeout:
        Per-request timeout in seconds (Anthropic only).

    Returns
    -------
    BaseLLMProvider
        The configured provider instance.

    Raises
    ------
    LLMConfigurationError
        If *name* is not a supported provider, or a required API key is
        missing for the selected provider.
    """
    normalized = name.lower()

    if normalized == "anthropic":
        if not api_key:
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY is required for the anthropic LLM provider."
            )
        return AnthropicProvider(
            api_key=api_key,
            model=model or _DEFAULT_ANTHROPIC_MODEL,
            timeout=timeout,
        )

    if normalized == "mock":
        return MockLLMProvider(model=model or _DEFAULT_MOCK_MODEL)

    raise LLMConfigurationError(
        f"Unsupported LLM_PROVIDER: {name!r}. Supported values: 'anthropic', 'mock'."
    )


__all__ = [
    "AnthropicProvider",
    "BaseLLMProvider",
    "LLMMessage",
    "LLMResponse",
    "MockLLMProvider",
    "get_llm_provider",
]
