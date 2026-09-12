"""Provider-agnostic LLM exceptions.

Every concrete LLM provider adapter (``app/llm/providers/*``) must catch its
own SDK-specific exceptions and re-raise one of these. No provider SDK
exception type may cross that boundary — callers (orchestration service,
API layer) only ever need to know about this hierarchy, exactly as
``app/rag/embeddings/openai.py`` never lets an ``openai.*`` exception escape
past its own module.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all provider-agnostic LLM errors."""


class LLMTimeoutError(LLMError):
    """The provider did not respond within the configured timeout."""


class LLMRateLimitError(LLMError):
    """The provider rejected the request due to rate limiting."""


class LLMProviderError(LLMError):
    """The provider returned an unexpected failure (5xx, network error, etc.)."""


class LLMConfigurationError(LLMError):
    """The LLM provider/configuration itself is invalid.

    Raised for both setup-time problems (unsupported provider name, missing
    API key) and request-time credential rejection (the provider reports the
    configured API key is invalid).
    """


class LLMContextError(LLMError):
    """The assembled prompt cannot fit within the configured token budget.

    Raised only when even the mandatory parts of a prompt (system
    instructions + the current question) exceed
    ``settings.LLM_CONTEXT_TOKEN_BUDGET`` on their own — i.e. after every
    optional/droppable part (retrieved evidence, conversation history) has
    already been removed. This is a fail-closed signal: the caller must not
    silently truncate the question itself or send a broken prompt.
    """
