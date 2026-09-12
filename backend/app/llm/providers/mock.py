"""Deterministic mock LLM provider for tests and offline development.

WARNING: This provider must NOT be treated as a benchmark or proof of real
model behavior. It exists solely to exercise the orchestration/prompt
pipeline without any network dependency, mirroring
``app.rag.embeddings.mock.MockEmbeddingProvider``'s role for M5.
"""

from __future__ import annotations

from app.llm.providers.base import BaseLLMProvider, LLMMessage, LLMResponse


class MockLLMProvider(BaseLLMProvider):
    """Records every call it receives and returns a deterministic response.

    Tests can inspect ``calls`` / ``last_messages`` / ``call_count`` to
    assert exactly what prompt was constructed and passed to the provider,
    and can set ``fixed_response`` or ``raise_error`` to control behavior
    without any network access.
    """

    def __init__(
        self,
        model: str = "mock-llm",
        fixed_response: str | None = None,
    ) -> None:
        self._model = model
        self.fixed_response = fixed_response
        self.raise_error: Exception | None = None
        self.calls: list[list[LLMMessage]] = []

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
        # Record the call BEFORE any potential raise so tests can still
        # assert what was about to be sent even when exercising failure paths.
        self.calls.append(messages)

        if self.raise_error is not None:
            raise self.raise_error

        content = self.fixed_response
        if content is None:
            # Deterministic content derived from the last user message so
            # tests can assert something meaningful without hardcoding text.
            last_user = next(
                (m.content for m in reversed(messages) if m.role == "user"), ""
            )
            content = f"[mock response to: {last_user[:200]}]"

        input_tokens = sum(len(m.content.split()) for m in messages)
        output_tokens = min(len(content.split()), max_tokens)

        return LLMResponse(
            content=content,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @property
    def last_messages(self) -> list[LLMMessage] | None:
        """The most recent call's message list, or ``None`` if never called."""
        return self.calls[-1] if self.calls else None

    @property
    def call_count(self) -> int:
        """Number of times ``complete()`` has been invoked."""
        return len(self.calls)
