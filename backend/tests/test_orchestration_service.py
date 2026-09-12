"""Tests for the Milestone 6 Phase 2 RAG -> LLM orchestration service.

Uses MockEmbeddingProvider + MockLLMProvider throughout -- no network calls
and no live Anthropic key required anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.exceptions import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.providers.mock import MockLLMProvider
from app.models.ingestion import RepositoryIngestion
from app.models.repository import Repository
from app.models.user import User
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.services.orchestration_service import (
    OrchestrationService,
    RepositoryNotIndexedError,
)
from app.services.rag_service import RAGService

_DEFAULT_KWARGS = {
    "token_budget": 12000,
    "min_relevance_score": 0.35,
    "max_history_messages": 8,
    "max_output_tokens": 2000,
}


async def _make_indexed_repository(
    db_session: AsyncSession,
    test_user: User,
    tmp_path: Path,
    *,
    files: dict[str, str],
    name: str = "orch-repo",
) -> tuple[Repository, int]:
    """Create an owned repository with one completed, indexed ingestion.

    Returns (repository, ingestion_id).
    """
    repo = Repository(
        owner_id=test_user.id,
        name=name,
        full_name=f"testuser/{name}",
        github_url=f"https://github.com/testuser/{name}",
        status="ready",
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    ingestion = RepositoryIngestion(repository_id=repo.id, status="completed")
    db_session.add(ingestion)
    await db_session.commit()
    await db_session.refresh(ingestion)

    for filename, content in files.items():
        (tmp_path / filename).write_text(content, encoding="utf-8")

    await RAGService.index_repository(
        db=db_session,
        repository_id=repo.id,
        ingestion_id=ingestion.id,
        source_root=tmp_path,
        embedding_provider=MockEmbeddingProvider(),
    )

    return repo, ingestion.id


class TestOrchestrationServiceHappyPath:
    """RAG -> prompt builder -> LLM, end to end against mocks."""

    @pytest.mark.asyncio
    async def test_ask_returns_answered_result_with_evidence_and_model(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo, ingestion_id = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={
                "auth.py": (
                    "def create_access_token(subject: str) -> str:\n"
                    "    return encode(subject)\n"
                )
            },
        )
        llm = MockLLMProvider(fixed_response="Here is the answer.")

        result = await OrchestrationService.ask(
            db=db_session,
            repository_id=repo.id,
            owner_id=test_user.id,
            question="create_access_token",
            llm_provider=llm,
            embedding_provider=MockEmbeddingProvider(),
            **_DEFAULT_KWARGS,
        )

        assert result.status == "answered"
        assert result.answer == "Here is the answer."
        assert result.ingestion_id == ingestion_id
        assert result.model == "mock-llm"
        assert len(result.evidence) >= 1
        assert result.evidence[0].file_path == "auth.py"
        assert result.input_tokens is not None
        assert result.output_tokens is not None
        assert llm.call_count == 1

    @pytest.mark.asyncio
    async def test_llm_receives_evidence_grounded_prompt(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo, _ = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"widget.py": "def render_widget():\n    return '<div></div>'\n"},
        )
        llm = MockLLMProvider()

        await OrchestrationService.ask(
            db=db_session,
            repository_id=repo.id,
            owner_id=test_user.id,
            question="render_widget",
            llm_provider=llm,
            embedding_provider=MockEmbeddingProvider(),
            **_DEFAULT_KWARGS,
        )

        assert llm.last_messages is not None
        assert llm.last_messages[0].role == "system"
        final_message = llm.last_messages[-1]
        assert final_message.role == "user"
        assert "widget.py" in final_message.content
        assert "render_widget" in final_message.content

    @pytest.mark.asyncio
    async def test_history_is_forwarded_to_prompt_builder(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        from app.llm.providers.base import LLMMessage

        repo, _ = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"main.py": "def main():\n    pass\n"},
        )
        llm = MockLLMProvider()
        history = [
            LLMMessage(role="user", content="earlier question"),
            LLMMessage(role="assistant", content="earlier answer"),
        ]

        await OrchestrationService.ask(
            db=db_session,
            repository_id=repo.id,
            owner_id=test_user.id,
            question="main",
            llm_provider=llm,
            embedding_provider=MockEmbeddingProvider(),
            history=history,
            **_DEFAULT_KWARGS,
        )

        assert llm.last_messages is not None
        contents = [m.content for m in llm.last_messages]
        assert "earlier question" in contents
        assert "earlier answer" in contents


class TestOrchestrationServiceInsufficientEvidence:
    """Insufficient-evidence gate prevents any LLM call."""

    @pytest.mark.asyncio
    async def test_no_qualifying_evidence_returns_insufficient_without_calling_llm(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo, ingestion_id = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"main.py": "def totally_unrelated_thing():\n    pass\n"},
        )
        llm = MockLLMProvider()

        result = await OrchestrationService.ask(
            db=db_session,
            repository_id=repo.id,
            owner_id=test_user.id,
            # An extremely high threshold guarantees nothing qualifies,
            # regardless of what the mock embedding/retrieval produces.
            question="something",
            llm_provider=llm,
            embedding_provider=MockEmbeddingProvider(),
            token_budget=12000,
            min_relevance_score=1.01,
            max_history_messages=8,
            max_output_tokens=2000,
        )

        assert result.status == "insufficient_evidence"
        assert result.evidence == []
        assert result.model is None
        assert result.ingestion_id == ingestion_id
        assert llm.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_retrieval_results_returns_insufficient(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        # An ingestion that completed but produced zero chunks (e.g. an
        # empty/unreadable source tree) must behave the same as "no
        # qualifying evidence", not crash.
        repo = Repository(
            owner_id=test_user.id,
            name="empty-repo",
            full_name="testuser/empty-repo",
            github_url="https://github.com/testuser/empty-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        ingestion = RepositoryIngestion(repository_id=repo.id, status="completed")
        db_session.add(ingestion)
        await db_session.commit()
        await db_session.refresh(ingestion)

        llm = MockLLMProvider()
        result = await OrchestrationService.ask(
            db=db_session,
            repository_id=repo.id,
            owner_id=test_user.id,
            question="anything",
            llm_provider=llm,
            embedding_provider=MockEmbeddingProvider(),
            **_DEFAULT_KWARGS,
        )

        assert result.status == "insufficient_evidence"
        assert llm.call_count == 0


class TestOrchestrationServiceMissingIngestion:
    """No completed ingestion is a distinct, clearly-typed failure."""

    @pytest.mark.asyncio
    async def test_no_completed_ingestion_raises_repository_not_indexed(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="never-ingested",
            full_name="testuser/never-ingested",
            github_url="https://github.com/testuser/never-ingested",
            status="pending",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        llm = MockLLMProvider()

        with pytest.raises(RepositoryNotIndexedError):
            await OrchestrationService.ask(
                db=db_session,
                repository_id=repo.id,
                owner_id=test_user.id,
                question="anything",
                llm_provider=llm,
                embedding_provider=MockEmbeddingProvider(),
                **_DEFAULT_KWARGS,
            )

        assert llm.call_count == 0


class TestOrchestrationServiceLLMFailures:
    """Provider failures propagate as Phase 1's provider-agnostic exceptions."""

    async def _repo_with_evidence(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> Repository:
        repo, _ = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"svc.py": "def process_payment():\n    pass\n"},
        )
        return repo

    @pytest.mark.asyncio
    async def test_llm_timeout_propagates(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo = await self._repo_with_evidence(db_session, test_user, tmp_path)
        llm = MockLLMProvider()
        llm.raise_error = LLMTimeoutError("simulated timeout")

        with pytest.raises(LLMTimeoutError):
            await OrchestrationService.ask(
                db=db_session,
                repository_id=repo.id,
                owner_id=test_user.id,
                question="process_payment",
                llm_provider=llm,
                embedding_provider=MockEmbeddingProvider(),
                **_DEFAULT_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_llm_rate_limit_propagates(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo = await self._repo_with_evidence(db_session, test_user, tmp_path)
        llm = MockLLMProvider()
        llm.raise_error = LLMRateLimitError("simulated rate limit")

        with pytest.raises(LLMRateLimitError):
            await OrchestrationService.ask(
                db=db_session,
                repository_id=repo.id,
                owner_id=test_user.id,
                question="process_payment",
                llm_provider=llm,
                embedding_provider=MockEmbeddingProvider(),
                **_DEFAULT_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_llm_provider_failure_propagates(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo = await self._repo_with_evidence(db_session, test_user, tmp_path)
        llm = MockLLMProvider()
        llm.raise_error = LLMProviderError("simulated 500")

        with pytest.raises(LLMProviderError):
            await OrchestrationService.ask(
                db=db_session,
                repository_id=repo.id,
                owner_id=test_user.id,
                question="process_payment",
                llm_provider=llm,
                embedding_provider=MockEmbeddingProvider(),
                **_DEFAULT_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_llm_configuration_error_propagates(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        repo = await self._repo_with_evidence(db_session, test_user, tmp_path)
        llm = MockLLMProvider()
        llm.raise_error = LLMConfigurationError("simulated bad key")

        with pytest.raises(LLMConfigurationError):
            await OrchestrationService.ask(
                db=db_session,
                repository_id=repo.id,
                owner_id=test_user.id,
                question="process_payment",
                llm_provider=llm,
                embedding_provider=MockEmbeddingProvider(),
                **_DEFAULT_KWARGS,
            )

    @pytest.mark.asyncio
    async def test_no_raw_sdk_exception_type_possible_here(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        """OrchestrationService never imports/depends on any provider SDK,
        so only LLMError subclasses can ever propagate from ``ask()``.
        This is a structural guarantee (verified in Phase 1's own provider
        tests); here we just confirm the plumbing doesn't add its own
        alternate exception type for provider failures.
        """
        repo = await self._repo_with_evidence(db_session, test_user, tmp_path)
        llm = MockLLMProvider()
        llm.raise_error = LLMProviderError("boom")

        try:
            await OrchestrationService.ask(
                db=db_session,
                repository_id=repo.id,
                owner_id=test_user.id,
                question="process_payment",
                llm_provider=llm,
                embedding_provider=MockEmbeddingProvider(),
                **_DEFAULT_KWARGS,
            )
        except Exception as exc:
            assert isinstance(exc, LLMProviderError)


class TestOrchestrationServiceRagContractUntouched:
    """M5's RAGService.search() contract is used, not modified."""

    @pytest.mark.asyncio
    async def test_search_called_with_hybrid_mode_by_default(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path, monkeypatch
    ) -> None:
        from app.schemas.rag import RetrievalMode

        repo, _ = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"a.py": "def foo():\n    pass\n"},
        )

        original_search = RAGService.search
        captured: dict[str, object] = {}

        async def _spy_search(cls, **kwargs):  # type: ignore[no-untyped-def]
            captured["mode"] = kwargs["request"].mode
            captured["min_score"] = kwargs["request"].min_score
            return await original_search(**kwargs)

        monkeypatch.setattr(RAGService, "search", classmethod(_spy_search))

        llm = MockLLMProvider()
        await OrchestrationService.ask(
            db=db_session,
            repository_id=repo.id,
            owner_id=test_user.id,
            question="foo",
            llm_provider=llm,
            embedding_provider=MockEmbeddingProvider(),
            **_DEFAULT_KWARGS,
        )

        assert captured["mode"] == RetrievalMode.HYBRID
        # OrchestrationService applies its own relevance threshold in the
        # prompt builder rather than pushing it into the RAG request, so
        # M5's own min_score contract is left at its default (None).
        assert captured["min_score"] is None

    @pytest.mark.asyncio
    async def test_returned_evidence_are_real_chunk_search_results(
        self, db_session: AsyncSession, test_user: User, tmp_path: Path
    ) -> None:
        from app.schemas.rag import ChunkSearchResult

        repo, _ = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"a.py": "def foo():\n    pass\n"},
        )
        llm = MockLLMProvider()

        result = await OrchestrationService.ask(
            db=db_session,
            repository_id=repo.id,
            owner_id=test_user.id,
            question="foo",
            llm_provider=llm,
            embedding_provider=MockEmbeddingProvider(),
            **_DEFAULT_KWARGS,
        )

        assert result.status == "answered"
        assert all(isinstance(c, ChunkSearchResult) for c in result.evidence)
