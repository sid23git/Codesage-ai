"""Tests for the M6 Phase 4 shared prompt/template helpers.

Pure functions only -- no database access, no network calls.
"""

from __future__ import annotations

from app.llm.prompt_templates import (
    ASK_SYSTEM_INSTRUCTIONS,
    EXPLAIN_SYSTEM_INSTRUCTIONS,
    REVIEW_SYSTEM_INSTRUCTIONS,
    build_explain_query,
    build_explain_question,
    build_review_query,
    build_review_question,
)


class TestSystemInstructions:
    """Each task type gets its own, distinct system instructions."""

    def test_all_three_are_distinct(self) -> None:
        texts = {
            ASK_SYSTEM_INSTRUCTIONS,
            EXPLAIN_SYSTEM_INSTRUCTIONS,
            REVIEW_SYSTEM_INSTRUCTIONS,
        }
        assert len(texts) == 3

    def test_all_share_the_core_hallucination_control_rules(self) -> None:
        for text in (
            ASK_SYSTEM_INSTRUCTIONS,
            EXPLAIN_SYSTEM_INSTRUCTIONS,
            REVIEW_SYSTEM_INSTRUCTIONS,
        ):
            assert "insufficient" in text.lower()
            assert "do not invent repository-specific facts" in text.lower()
            assert "never claim to have executed" in text.lower()

    def test_review_instructions_mention_untrusted_user_input(self) -> None:
        assert "untrusted input" in REVIEW_SYSTEM_INSTRUCTIONS.lower()


class TestBuildExplainQuery:
    """Retrieval query construction for /explain."""

    def test_prefers_symbol_alone_so_the_exact_match_bonus_can_fire(self) -> None:
        # fuse()'s exact-symbol-match bonus only fires when the *entire*
        # query equals chunk.name -- so the query must be the symbol
        # alone, never combined with other text.
        query = build_explain_query(
            file_path="app/main.py", symbol="run", question="what does it do"
        )
        assert query == "run"

    def test_falls_back_to_question_when_no_symbol(self) -> None:
        query = build_explain_query(
            file_path="app/main.py", symbol=None, question="what does main do"
        )
        assert query == "what does main do"

    def test_falls_back_to_file_stem_when_nothing_else_given(self) -> None:
        query = build_explain_query(
            file_path="app/services/foo.py", symbol=None, question=None
        )
        assert query == "foo"

    def test_never_empty(self) -> None:
        query = build_explain_query(file_path="x.py", symbol=None, question=None)
        assert query.strip() != ""

    def test_truncated_to_1000_chars(self) -> None:
        query = build_explain_query(file_path="x.py", symbol=None, question="q" * 5000)
        assert len(query) <= 1000


class TestBuildExplainQuestion:
    """User-facing instruction text for /explain."""

    def test_includes_file_path(self) -> None:
        text = build_explain_question(
            file_path="app/main.py",
            start_line=None,
            end_line=None,
            symbol=None,
            question=None,
        )
        assert "app/main.py" in text

    def test_includes_line_range_when_given(self) -> None:
        text = build_explain_question(
            file_path="app/main.py",
            start_line=10,
            end_line=20,
            symbol=None,
            question=None,
        )
        assert "10-20" in text

    def test_single_line_when_start_equals_end(self) -> None:
        text = build_explain_question(
            file_path="app/main.py",
            start_line=10,
            end_line=10,
            symbol=None,
            question=None,
        )
        assert "app/main.py:10" in text
        assert "10-10" not in text

    def test_includes_symbol_when_given(self) -> None:
        text = build_explain_question(
            file_path="app/main.py",
            start_line=None,
            end_line=None,
            symbol="run",
            question=None,
        )
        assert "symbol: run" in text

    def test_includes_user_question_when_given(self) -> None:
        text = build_explain_question(
            file_path="app/main.py",
            start_line=None,
            end_line=None,
            symbol=None,
            question="why is this async",
        )
        assert "why is this async" in text


class TestBuildReviewQuery:
    """Retrieval query construction for /review."""

    def test_prefers_symbol_alone_so_the_exact_match_bonus_can_fire(self) -> None:
        query = build_review_query(
            file_path="app/main.py", symbol="run", user_code="def unrelated(): pass"
        )
        assert query == "run"

    def test_falls_back_to_file_stem_when_no_symbol(self) -> None:
        query = build_review_query(
            file_path="app/services/foo.py", symbol=None, user_code=None
        )
        assert query == "foo"

    def test_derives_from_user_code_when_no_repo_target(self) -> None:
        query = build_review_query(
            file_path=None, symbol=None, user_code="def my_func():\n    pass"
        )
        assert "my_func" in query

    def test_never_empty(self) -> None:
        query = build_review_query(file_path=None, symbol=None, user_code=None)
        assert query.strip() != ""


class TestBuildReviewQuestion:
    """User-facing instruction text for /review."""

    def test_includes_focus(self) -> None:
        text = build_review_question(
            focus="security",
            file_path=None,
            symbol=None,
            start_line=None,
            end_line=None,
            user_code=None,
        )
        assert "security" in text

    def test_includes_repository_target_when_given(self) -> None:
        text = build_review_question(
            focus="general",
            file_path="app/main.py",
            symbol="run",
            start_line=1,
            end_line=5,
            user_code=None,
        )
        assert "app/main.py:1-5" in text
        assert "symbol: run" in text

    def test_labels_user_code_as_untrusted_input(self) -> None:
        text = build_review_question(
            focus="general",
            file_path=None,
            symbol=None,
            start_line=None,
            end_line=None,
            user_code="def x(): pass",
        )
        assert "User-provided code" in text
        assert "untrusted input" in text
        assert "def x(): pass" in text

    def test_includes_json_response_format_instructions(self) -> None:
        text = build_review_question(
            focus="general",
            file_path="a.py",
            symbol=None,
            start_line=None,
            end_line=None,
            user_code=None,
        )
        assert "JSON object" in text
        assert '"findings"' in text
