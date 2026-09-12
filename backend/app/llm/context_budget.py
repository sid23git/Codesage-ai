"""Provider-agnostic context/token budget utility for LLM prompt construction.

MVP token counting note
------------------------
This module does **not** use a real provider tokenizer. Anthropic does not
publish an offline tokenizer, and pulling in OpenAI's ``tiktoken`` here would
both add an unnecessary dependency for this purpose and not accurately
reflect Claude's own tokenization anyway. Instead, ``estimate_tokens()``
uses a conservative, deterministic heuristic: roughly 4 characters per
token, rounded up. This is the same order-of-magnitude approximation
commonly published by both OpenAI and Anthropic for rough sizing, and is
deliberately biased to slightly OVER-estimate (ceiling rounding plus a
small flat per-message overhead) so the hard ceiling in
``settings.LLM_CONTEXT_TOKEN_BUDGET`` is never silently exceeded in
practice. If a later milestone wires in a real provider tokenizer, only
``estimate_tokens()`` needs to change — everything else here, and in
``app.llm.prompt_builder``, is written against the token counts it
returns rather than against character counts directly.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TypeVar

from app.llm.providers.base import LLMMessage

_CHARS_PER_TOKEN = 4.0
_PER_MESSAGE_OVERHEAD_TOKENS = 4  # flat allowance for role/formatting overhead

T = TypeVar("T")


def estimate_tokens(text: str) -> int:
    """Conservative, dependency-free token count estimate for *text*.

    See the module docstring for why this heuristic — not a real
    tokenizer — is used at this stage. Deterministic: the same input
    always yields the same output.
    """
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def estimate_message_tokens(message: LLMMessage) -> int:
    """Estimate the token cost of a single ``LLMMessage``, including overhead."""
    return estimate_tokens(message.content) + _PER_MESSAGE_OVERHEAD_TOKENS


def estimate_messages_tokens(messages: Sequence[LLMMessage]) -> int:
    """Estimate the total token cost of an ordered list of messages."""
    return sum(estimate_message_tokens(m) for m in messages)


class TokenBudget:
    """Enforces a hard upper bound on assembled LLM input context.

    This class is a pure measuring/selection *mechanism* — it has no
    opinion about what content matters most. Callers decide priority
    ordering (e.g. highest-relevance evidence first, most-recent history
    first) and hand candidates to :meth:`fit_greedy` already in that order.
    """

    def __init__(self, max_tokens: int) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer.")
        self.max_tokens = max_tokens

    def remaining(self, used_tokens: int) -> int:
        """Tokens still available given *used_tokens* already committed."""
        return max(0, self.max_tokens - used_tokens)

    def fits(self, used_tokens: int, candidate_tokens: int) -> bool:
        """Whether *candidate_tokens* more would still be within budget."""
        return used_tokens + candidate_tokens <= self.max_tokens

    def fit_greedy(
        self,
        used_tokens: int,
        candidates: Sequence[T],
        token_fn: Callable[[T], int],
    ) -> tuple[list[T], int]:
        """Greedily accept *candidates*, in the given order, while they fit.

        The first candidate that would overflow the remaining budget stops
        selection — later (lower-priority, per the caller's own ordering)
        candidates are never used to "fill the gap" left by a skipped one.
        This keeps results predictable and order-respecting rather than
        optimizing for a best-fit/knapsack-style packing.

        Parameters
        ----------
        used_tokens:
            Tokens already committed (e.g. system instructions + the
            current question) before any of *candidates* are considered.
        candidates:
            Items to consider, already in priority order (highest priority
            first).
        token_fn:
            Callable returning the token cost of a single candidate.

        Returns
        -------
        tuple[list[T], int]
            ``(selected_candidates, total_tokens_used_including_selected)``
        """
        selected: list[T] = []
        running_total = used_tokens

        for candidate in candidates:
            cost = token_fn(candidate)
            if running_total + cost > self.max_tokens:
                break
            selected.append(candidate)
            running_total += cost

        return selected, running_total
