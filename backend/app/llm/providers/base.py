"""Base LLM provider interface and provider-agnostic message/response types.

Mirrors ``app/rag/embeddings/base.py``'s abstraction: every concrete
provider adapter must expose exactly this interface, and no provider SDK
type (Anthropic, OpenAI, Gemini, ...) may cross it in either direction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

LLMRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    """A single provider-agnostic chat message."""

    role: LLMRole
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """Provider-agnostic result of a completion call."""

    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class BaseLLMProvider(ABC):
    """Abstract interface for LLM chat/completion generation."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Canonical model identifier this provider instance is configured for."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate a completion for *messages*.

        Parameters
        ----------
        messages:
            Ordered conversation messages (system/user/assistant roles).
        max_tokens:
            Maximum number of tokens to generate in the response.
        temperature:
            Sampling temperature (0.0 = deterministic).

        Returns
        -------
        LLMResponse
            Provider-agnostic completion result.

        Raises
        ------
        LLMError
            Or one of its subclasses (see ``app.llm.exceptions``) — never a
            provider SDK exception.
        """
        ...
