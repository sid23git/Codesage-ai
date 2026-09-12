"""Tests for the Milestone 6 Phase 2 context-budget and prompt-builder layers.

No database access and no network calls anywhere in this file — both
modules under test are pure/deterministic by design.
"""

from __future__ import annotations

import pytest

from app.llm.context_budget import (
    TokenBudget,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
)
from app.llm.exceptions import LLMContextError
from app.llm.prompt_builder import (
    InsufficientEvidenceError,
    PromptBuilder,
    select_evidence,
)
from app.llm.providers.base import LLMMessage
from app.schemas.rag import ChunkSearchResult


def _chunk(
    chunk_id: int,
    *,
    score: float,
    file_path: str = "app/main.py",
    start_line: int = 1,
    end_line: int = 10,
    language: str | None = "Python",
    chunk_type: str = "function",
    name: str | None = "some_function",
    chunk_text: str = "def some_function():\n    pass",
    retrieval_sources: list[str] | None = None,
) -> ChunkSearchResult:
    return ChunkSearchResult(
        chunk_id=chunk_id,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        language=language,
        chunk_type=chunk_type,
        name=name,
        chunk_text=chunk_text,
        score=score,
        retrieval_sources=retrieval_sources or ["semantic"],
    )


class TestEstimateTokens:
    """Test the dependency-free token estimation primitive."""

    def test_empty_string_is_zero_tokens(self) -> None:
        assert estimate_tokens("") == 0

    def test_deterministic_for_same_input(self) -> None:
        text = "def calculate_total(items: list[int]) -> int:\n    return sum(items)"
        assert estimate_tokens(text) == estimate_tokens(text)

    def test_scales_with_length(self) -> None:
        short = "hello"
        long = "hello world " * 50
        assert estimate_tokens(long) > estimate_tokens(short)

    def test_rounds_up_conservatively(self) -> None:
        # 1 character is less than one "token unit" (4 chars) but must
        # still cost at least 1 token, never 0.
        assert estimate_tokens("x") == 1

    def test_message_tokens_include_overhead(self) -> None:
        msg = LLMMessage(role="user", content="hi")
        assert estimate_message_tokens(msg) > estimate_tokens("hi")

    def test_messages_total_is_sum_of_parts(self) -> None:
        messages = [
            LLMMessage(role="system", content="a" * 20),
            LLMMessage(role="user", content="b" * 40),
        ]
        assert estimate_messages_tokens(messages) == sum(
            estimate_message_tokens(m) for m in messages
        )


class TestTokenBudget:
    """Test the generic priority-ordered budget-fitting mechanism."""

    def test_rejects_non_positive_budget(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            TokenBudget(0)
        with pytest.raises(ValueError, match="positive"):
            TokenBudget(-5)

    def test_remaining_and_fits(self) -> None:
        budget = TokenBudget(100)
        assert budget.remaining(40) == 60
        assert budget.remaining(150) == 0  # never negative
        assert budget.fits(40, 60) is True
        assert budget.fits(40, 61) is False

    def test_fit_greedy_accepts_while_under_budget(self) -> None:
        budget = TokenBudget(10)
        candidates = ["aa", "bb", "cc"]  # each costs len() == 2 tokens here
        selected, used = budget.fit_greedy(0, candidates, token_fn=len)
        assert selected == ["aa", "bb", "cc"]
        assert used == 6

    def test_fit_greedy_stops_at_first_overflow_and_does_not_backfill(self) -> None:
        budget = TokenBudget(5)
        # costs: 3, 4, 1 -- second item overflows (3+4=7 > 5), so even though
        # the third item (cost 1) would fit on its own, it must NOT be used
        # to "fill the gap" left by skipping the second.
        candidates = [("a", 3), ("b", 4), ("c", 1)]
        selected, used = budget.fit_greedy(0, candidates, token_fn=lambda c: c[1])
        assert selected == [("a", 3)]
        assert used == 3

    def test_fit_greedy_respects_already_used_tokens(self) -> None:
        budget = TokenBudget(10)
        selected, used = budget.fit_greedy(8, ["xx", "yy"], token_fn=len)
        assert selected == ["xx"]
        assert used == 10

    def test_fit_greedy_is_deterministic(self) -> None:
        budget = TokenBudget(7)
        candidates = ["a", "bb", "ccc", "dddd"]
        result1 = budget.fit_greedy(0, candidates, token_fn=len)
        result2 = budget.fit_greedy(0, candidates, token_fn=len)
        assert result1 == result2


class TestSelectEvidence:
    """Test evidence filtering, dedup, and deterministic ordering."""

    def test_drops_chunks_below_threshold(self) -> None:
        chunks = [_chunk(1, score=0.9), _chunk(2, score=0.1)]
        result = select_evidence(chunks, min_relevance_score=0.35)
        assert [c.chunk_id for c in result] == [1]

    def test_drops_unusable_empty_text_chunks(self) -> None:
        chunks = [
            _chunk(1, score=0.9, chunk_text="   "),
            _chunk(2, score=0.8, chunk_text="real code"),
        ]
        result = select_evidence(chunks, min_relevance_score=0.35)
        assert [c.chunk_id for c in result] == [2]

    def test_deduplicates_by_chunk_id_keeping_highest_score(self) -> None:
        chunks = [
            _chunk(1, score=0.5),
            _chunk(1, score=0.9),  # same chunk_id, higher score
        ]
        result = select_evidence(chunks, min_relevance_score=0.0)
        assert len(result) == 1
        assert result[0].score == 0.9

    def test_deterministic_ordering_by_score_desc_then_id(self) -> None:
        chunks = [_chunk(3, score=0.5), _chunk(1, score=0.9), _chunk(2, score=0.9)]
        result = select_evidence(chunks, min_relevance_score=0.0)
        assert [c.chunk_id for c in result] == [1, 2, 3]

    def test_ordering_independent_of_input_order(self) -> None:
        chunks_a = [_chunk(1, score=0.7), _chunk(2, score=0.9), _chunk(3, score=0.5)]
        chunks_b = [_chunk(3, score=0.5), _chunk(1, score=0.7), _chunk(2, score=0.9)]
        assert [c.chunk_id for c in select_evidence(chunks_a, 0.0)] == [
            c.chunk_id for c in select_evidence(chunks_b, 0.0)
        ]

    def test_empty_input_returns_empty(self) -> None:
        assert select_evidence([], min_relevance_score=0.35) == []


class TestPromptBuilder:
    """Test full prompt assembly: formatting, budgeting, history, gating."""

    def _builder(
        self,
        *,
        token_budget: int = 12000,
        min_relevance_score: float = 0.35,
        max_history_messages: int = 8,
    ) -> PromptBuilder:
        return PromptBuilder(
            token_budget=token_budget,
            min_relevance_score=min_relevance_score,
            max_history_messages=max_history_messages,
        )

    def test_evidence_formatting_includes_all_metadata(self) -> None:
        builder = self._builder()
        chunk = _chunk(
            1,
            score=0.82,
            file_path="app/services/rag_service.py",
            start_line=118,
            end_line=157,
            language="Python",
            name="index_repository",
            chunk_text="async def index_repository(...): ...",
        )
        result = builder.build(
            question="What does index_repository do?", evidence=[chunk]
        )

        user_message = result.messages[-1]
        assert "app/services/rag_service.py:118-157" in user_message.content
        assert "language=Python" in user_message.content
        assert "symbol=index_repository" in user_message.content
        assert "score=0.82" in user_message.content
        assert "async def index_repository" in user_message.content

    def test_system_message_is_first_and_separate_from_evidence(self) -> None:
        builder = self._builder()
        result = builder.build(
            question="q",
            evidence=[_chunk(1, score=0.9, chunk_text="def unique_marker(): pass")],
        )
        assert result.messages[0].role == "system"
        # The system message states the *policy* (it legitimately mentions
        # "Repository evidence" by name), but must not contain the actual
        # rendered evidence block or citation markers -- those belong only
        # in the final user message.
        assert "[Source" not in result.messages[0].content
        assert "def unique_marker" not in result.messages[0].content

    def test_question_is_present_in_final_user_message(self) -> None:
        builder = self._builder()
        result = builder.build(
            question="How does auth work?", evidence=[_chunk(1, score=0.9)]
        )
        assert "Question: How does auth work?" in result.messages[-1].content

    def test_source_metadata_preserved_on_evidence_used(self) -> None:
        builder = self._builder()
        chunk = _chunk(7, score=0.9, file_path="x.py", start_line=3, end_line=9)
        result = builder.build(question="q", evidence=[chunk])
        assert result.evidence_used == [chunk]
        assert result.evidence_used[0].chunk_id == 7
        assert result.evidence_used[0].file_path == "x.py"

    def test_relevance_threshold_excludes_low_score_chunks(self) -> None:
        builder = self._builder(min_relevance_score=0.5)
        high = _chunk(1, score=0.9)
        low = _chunk(2, score=0.2)
        result = builder.build(question="q", evidence=[high, low])
        assert [c.chunk_id for c in result.evidence_used] == [1]

    def test_duplicate_evidence_deduplicated(self) -> None:
        builder = self._builder()
        chunk_a = _chunk(1, score=0.6)
        chunk_b = _chunk(1, score=0.9)  # same id, different score instance
        result = builder.build(question="q", evidence=[chunk_a, chunk_b])
        assert len(result.evidence_used) == 1
        assert result.evidence_used[0].score == 0.9

    def test_deterministic_ordering_of_evidence_used(self) -> None:
        builder = self._builder()
        chunks = [_chunk(3, score=0.4), _chunk(1, score=0.9), _chunk(2, score=0.6)]
        result = builder.build(question="q", evidence=chunks)
        assert [c.chunk_id for c in result.evidence_used] == [1, 2, 3]

    def test_insufficient_evidence_raises_when_all_below_threshold(self) -> None:
        builder = self._builder(min_relevance_score=0.5)
        with pytest.raises(InsufficientEvidenceError):
            builder.build(question="q", evidence=[_chunk(1, score=0.1)])

    def test_insufficient_evidence_raises_on_empty_evidence(self) -> None:
        builder = self._builder()
        with pytest.raises(InsufficientEvidenceError):
            builder.build(question="q", evidence=[])

    def test_context_budget_never_exceeded_with_many_chunks(self) -> None:
        budget_tokens = 500
        builder = self._builder(token_budget=budget_tokens)
        chunks = [_chunk(i, score=0.9, chunk_text="x" * 300) for i in range(1, 20)]
        result = builder.build(question="q", evidence=chunks)

        assert estimate_messages_tokens(result.messages) <= budget_tokens
        # Budget pressure must have actually excluded some candidates.
        assert len(result.evidence_used) < len(chunks)

    def test_oversized_single_chunk_excluded_others_still_included(self) -> None:
        # fit_greedy is priority-order-respecting with no backfill (a
        # deliberate anti-"budget gaming" choice — see context_budget.py),
        # so the smaller chunk must outrank the oversized one to be tried
        # first: [small(0.9), huge(0.5)] -> small fits, huge overflows and
        # is excluded without blocking small.
        builder = self._builder(token_budget=400)
        small = _chunk(2, score=0.9, chunk_text="small evidence")
        huge = _chunk(1, score=0.5, chunk_text="z" * 5000)
        result = builder.build(question="q", evidence=[small, huge])

        assert 2 in [c.chunk_id for c in result.evidence_used]
        assert 1 not in [c.chunk_id for c in result.evidence_used]

    def test_oversized_single_chunk_as_only_evidence_is_insufficient(self) -> None:
        # Budget large enough for the mandatory system+question skeleton
        # (~251 tokens) but not for the oversized chunk on top of it.
        builder = self._builder(token_budget=300)
        huge = _chunk(1, score=0.99, chunk_text="z" * 5000)
        with pytest.raises(InsufficientEvidenceError):
            builder.build(question="q", evidence=[huge])

    def test_history_included_in_chronological_order(self) -> None:
        builder = self._builder()
        history = [
            LLMMessage(role="user", content="first turn"),
            LLMMessage(role="assistant", content="first reply"),
            LLMMessage(role="user", content="second turn"),
        ]
        result = builder.build(
            question="third turn", evidence=[_chunk(1, score=0.9)], history=history
        )
        assert result.history_used == history
        # system, then history (chronological), then the final combined
        # evidence+question user message.
        assert result.messages == [result.messages[0], *history, result.messages[-1]]

    def test_history_truncated_to_max_history_messages(self) -> None:
        builder = self._builder(max_history_messages=2)
        history = [
            LLMMessage(role="user", content="turn 1"),
            LLMMessage(role="assistant", content="reply 1"),
            LLMMessage(role="user", content="turn 2"),
            LLMMessage(role="assistant", content="reply 2"),
        ]
        result = builder.build(
            question="q", evidence=[_chunk(1, score=0.9)], history=history
        )
        # Only the most recent 2 messages are even considered.
        assert result.history_used == history[-2:]

    def test_history_dropped_oldest_first_under_budget_pressure(self) -> None:
        # Budget fits the mandatory skeleton (~251 tokens) + the one small
        # evidence chunk (~21 tokens) + only the most recent history
        # message (~7 tokens) -- not enough remains for the two older,
        # much longer messages, which must be dropped oldest-first.
        builder = self._builder(token_budget=292, max_history_messages=8)
        history = [
            LLMMessage(role="user", content="oldest turn " + "a" * 100),
            LLMMessage(role="assistant", content="middle turn " + "b" * 100),
            LLMMessage(role="user", content="newest turn"),
        ]
        result = builder.build(
            question="q",
            evidence=[_chunk(1, score=0.9, chunk_text="ev")],
            history=history,
        )
        assert result.history_used == [history[-1]]

    def test_no_history_provided_is_fine(self) -> None:
        builder = self._builder()
        result = builder.build(question="q", evidence=[_chunk(1, score=0.9)])
        assert result.history_used == []

    def test_evidence_considered_reflects_input_size_not_selected_size(self) -> None:
        builder = self._builder()
        chunks = [_chunk(1, score=0.9), _chunk(2, score=0.01)]
        result = builder.build(question="q", evidence=chunks)
        assert result.evidence_considered == 2
        assert len(result.evidence_used) == 1

    def test_llm_context_error_when_question_alone_exceeds_budget(self) -> None:
        builder = self._builder(token_budget=20)
        with pytest.raises(LLMContextError):
            builder.build(question="x" * 5000, evidence=[_chunk(1, score=0.9)])

    def test_tokens_used_within_declared_budget(self) -> None:
        builder = self._builder(token_budget=12000)
        result = builder.build(question="q", evidence=[_chunk(1, score=0.9)])
        assert result.tokens_used <= 12000
