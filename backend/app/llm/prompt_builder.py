"""Pure prompt/context construction for RAG-grounded LLM completions.

This module performs **no database access and no network calls**. It takes
a question, already-retrieved M5 evidence (``ChunkSearchResult``), and
optional conversation history, and deterministically assembles a
token-budgeted list of ``LLMMessage``s ready to hand to a
``BaseLLMProvider``.

Responsibility boundary
------------------------
- Evidence *relevance filtering* (against ``LLM_MIN_RELEVANCE_SCORE``),
  deduplication, and ordering happen here (:func:`select_evidence`).
- The *decision* of what to do when no evidence qualifies (e.g. return an
  insufficient-evidence response instead of calling the LLM) belongs to the
  caller (``app.services.orchestration_service``) — this module only
  *signals* that condition by raising :class:`InsufficientEvidenceError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.llm.context_budget import (
    TokenBudget,
    estimate_message_tokens,
    estimate_tokens,
)
from app.llm.exceptions import LLMContextError
from app.llm.providers.base import LLMMessage
from app.schemas.rag import ChunkSearchResult

_SYSTEM_INSTRUCTIONS = (
    "You are CodeSage, an AI assistant that answers questions about a "
    "specific software repository using retrieved evidence from that "
    "repository.\n\n"
    "Rules you must follow:\n"
    '- Answer using the "Repository evidence" provided in the user\'s '
    "message. Do not invent repository-specific facts (file names, "
    "function behavior, configuration values, etc.) that are not "
    "supported by the evidence.\n"
    "- If the provided evidence is insufficient to answer confidently, "
    "say so explicitly instead of guessing.\n"
    "- When you state a fact drawn from the evidence, cite its source "
    'location using the "file_path:start_line-end_line" format shown in '
    "the evidence labels.\n"
    "- Clearly distinguish between facts you found in the repository "
    "evidence and general software-engineering guidance you provide from "
    "your own knowledge; label general guidance as such.\n"
    "- Never claim to have executed code, run tests, or run commands. "
    "You can only read and reason about the text provided to you."
)


class InsufficientEvidenceError(Exception):
    """No retrieved evidence qualified to ground an answer.

    Raised when either no chunk meets the configured minimum relevance
    score, or no qualifying chunk's formatted evidence block fits within
    the remaining token budget. The caller (orchestration layer) must
    treat this as a signal to return a defined insufficient-evidence
    result — never as a reason to fall back to unsupported general
    knowledge.
    """


@dataclass(frozen=True)
class PromptBuildResult:
    """The assembled prompt plus enough metadata to act on it afterwards."""

    messages: list[LLMMessage]
    evidence_used: list[ChunkSearchResult]
    history_used: list[LLMMessage]
    evidence_considered: int
    tokens_used: int


def select_evidence(
    evidence: Sequence[ChunkSearchResult],
    min_relevance_score: float,
) -> list[ChunkSearchResult]:
    """Filter, deduplicate, and deterministically order evidence chunks.

    - Drops chunks scoring below *min_relevance_score*.
    - Drops "unusable" chunks whose text is empty/whitespace-only.
    - Deduplicates by ``chunk_id``, keeping the highest-scored occurrence
      (defensive: normal callers only pass each chunk once, since
      ``RAGService.search()``'s own fusion step already deduplicates by
      chunk id, but this function does not assume that).
    - Orders by score descending, then ``chunk_id`` ascending as a stable
      tie-break, so results are fully deterministic regardless of input
      order.
    """
    best_by_id: dict[int, ChunkSearchResult] = {}

    for chunk in evidence:
        if chunk.score < min_relevance_score:
            continue
        if not chunk.chunk_text.strip():
            continue
        existing = best_by_id.get(chunk.chunk_id)
        if existing is None or chunk.score > existing.score:
            best_by_id[chunk.chunk_id] = chunk

    return sorted(best_by_id.values(), key=lambda c: (-c.score, c.chunk_id))


def _format_evidence_block(rank: int, chunk: ChunkSearchResult) -> str:
    """Render one evidence chunk with citation metadata a model (and a
    human reading the persisted evidence later) can use to locate it.
    """
    location = f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}"
    meta = [f"Source {rank}: {location}"]
    if chunk.language:
        meta.append(f"language={chunk.language}")
    if chunk.name:
        meta.append(f"symbol={chunk.name}")
    meta.append(f"score={chunk.score:.2f}")
    header = "[" + ", ".join(meta) + "]"
    return f"{header}\n{chunk.chunk_text}"


class PromptBuilder:
    """Assembles token-budgeted, citation-formatted prompts.

    Instantiated once with the resolved configuration for a request
    (mirroring how ``VectorRetriever``/``KeywordRetriever`` are constructed
    fresh per call in M5), then ``build()`` is called once per turn.
    """

    def __init__(
        self,
        *,
        token_budget: int,
        min_relevance_score: float,
        max_history_messages: int,
    ) -> None:
        self._budget = TokenBudget(token_budget)
        self._min_relevance_score = min_relevance_score
        self._max_history_messages = max_history_messages

    def build(
        self,
        *,
        question: str,
        evidence: Sequence[ChunkSearchResult],
        history: Sequence[LLMMessage] | None = None,
    ) -> PromptBuildResult:
        """Build a bounded prompt for *question*, grounded in *evidence*.

        Parameters
        ----------
        question:
            The current user question (never truncated or dropped).
        evidence:
            Candidate ``ChunkSearchResult`` rows from ``RAGService.search()``
            — may be empty, may contain chunks below the relevance
            threshold, and is not assumed to be pre-deduplicated.
        history:
            Optional prior conversation turns, oldest-first. Truncated to
            the most recent ``max_history_messages`` before budgeting.

        Returns
        -------
        PromptBuildResult

        Raises
        ------
        InsufficientEvidenceError
            If no evidence qualifies (below threshold, unusable, or none
            fits within the token budget at all).
        LLMContextError
            If the system instructions + question alone (with zero
            evidence and zero history) already exceed the token budget.
        """
        system_message = LLMMessage(role="system", content=_SYSTEM_INSTRUCTIONS)

        qualifying = select_evidence(evidence, self._min_relevance_score)
        if not qualifying:
            raise InsufficientEvidenceError(
                "No retrieved evidence met the minimum relevance score."
            )

        evidence_pairs = [
            (chunk, _format_evidence_block(rank, chunk))
            for rank, chunk in enumerate(qualifying, start=1)
        ]

        # Mandatory skeleton: system instructions + the wrapper text and
        # question that will surround whatever evidence ends up included.
        # This must never be dropped -- if it alone overflows the budget,
        # fail closed rather than truncate the user's actual question.
        question_wrapper_tokens = estimate_tokens(
            f"Repository evidence:\n\n\n\n---\n\nQuestion: {question}"
        )
        base_used = estimate_message_tokens(system_message) + question_wrapper_tokens

        if base_used > self._budget.max_tokens:
            raise LLMContextError(
                "The system instructions and current question alone exceed "
                "the configured LLM_CONTEXT_TOKEN_BUDGET; the question is "
                "too large to send even without any evidence or history."
            )

        included_evidence, used_after_evidence = self._budget.fit_greedy(
            base_used,
            evidence_pairs,
            token_fn=lambda pair: estimate_tokens(pair[1]),
        )

        if not included_evidence:
            # Qualifying evidence existed, but none of it fits the budget
            # (e.g. a single oversized chunk) -- there is nothing usable to
            # ground an answer in, so this is treated the same as "no
            # qualifying evidence at all".
            raise InsufficientEvidenceError(
                "Qualifying evidence exists but none of it fits within the "
                "configured token budget."
            )

        evidence_used = [chunk for chunk, _ in included_evidence]

        # History: truncate to the most recent N, then greedily fill
        # whatever budget remains, preferring the MOST recent turns (so
        # under pressure the oldest history is dropped first) -- then
        # restore chronological order for the final prompt.
        truncated_history = (
            list(history)[-self._max_history_messages :] if history else []
        )
        recent_first = list(reversed(truncated_history))
        included_recent_first, tokens_used = self._budget.fit_greedy(
            used_after_evidence,
            recent_first,
            token_fn=estimate_message_tokens,
        )
        history_used = list(reversed(included_recent_first))

        evidence_section = "\n\n".join(block for _, block in included_evidence)
        user_content = (
            f"Repository evidence:\n\n{evidence_section}\n\n---\n\nQuestion: {question}"
        )
        final_message = LLMMessage(role="user", content=user_content)

        messages = [system_message, *history_used, final_message]

        return PromptBuildResult(
            messages=messages,
            evidence_used=evidence_used,
            history_used=history_used,
            evidence_considered=len(evidence),
            tokens_used=tokens_used,
        )
