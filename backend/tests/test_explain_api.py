"""Integration tests for the M6 Phase 4 /explain endpoint.

Uses MockLLMProvider (injected via FastAPI dependency_overrides) and
MockEmbeddingProvider (the app's own default) throughout -- no network
calls and no live Anthropic key required anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_provider
from app.llm.exceptions import LLMProviderError
from app.llm.providers.mock import MockLLMProvider
from app.main import app
from app.models.ingestion import RepositoryIngestion
from app.models.repository import Repository
from app.models.user import User
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.services.rag_service import RAGService


async def _make_indexed_repository(
    db_session: AsyncSession,
    owner: User,
    tmp_path: Path,
    *,
    files: dict[str, str],
    name: str = "explain-repo",
) -> Repository:
    repo = Repository(
        owner_id=owner.id,
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
    return repo


def _override_llm(llm: MockLLMProvider) -> None:
    app.dependency_overrides[get_llm_provider] = lambda: llm


class TestExplainEndpointHappyPath:
    """Normal explanation, targeted by file, line range, and symbol."""

    @pytest.mark.asyncio
    async def test_explain_whole_file(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        repo = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={
                "auth.py": ("def create_access_token(subject):\n    return subject\n")
            },
        )
        _override_llm(MockLLMProvider(fixed_response="This creates a JWT token."))

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "auth.py", "symbol": "create_access_token"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "answered"
        assert payload["explanation"] == "This creates a JWT token."
        assert len(payload["evidence"]) >= 1
        assert payload["evidence"][0]["file_path"] == "auth.py"
        assert payload["model"] == "mock-llm"
        # No conversation_id was supplied -- nothing persisted.
        assert payload["conversation_id"] is None

    @pytest.mark.asyncio
    async def test_explain_with_line_range_target(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        repo = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"main.py": "def main():\n    pass\n"},
        )
        _override_llm(MockLLMProvider(fixed_response="It's the entry point."))

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "main.py", "start_line": 1, "end_line": 2},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "answered"

    @pytest.mark.asyncio
    async def test_explain_with_symbol_and_question(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        repo = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"svc.py": "def process_payment():\n    pass\n"},
        )
        llm = MockLLMProvider(fixed_response="It processes a payment.")
        _override_llm(llm)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={
                "file_path": "svc.py",
                "symbol": "process_payment",
                "question": "does it validate the amount?",
            },
        )

        assert response.status_code == 200
        assert llm.last_messages is not None
        final_message = llm.last_messages[-1]
        assert "process_payment" in final_message.content
        assert "does it validate the amount?" in final_message.content

    @pytest.mark.asyncio
    async def test_explain_persists_to_conversation_when_id_given(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        repo = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"main.py": "def main():\n    pass\n"},
        )
        _override_llm(MockLLMProvider(fixed_response="first turn"))
        first = client.post(
            f"/api/v1/repositories/{repo.id}/ask",
            headers=auth_headers,
            json={"message": "main"},
        )
        conversation_id = first.json()["conversation_id"]

        _override_llm(MockLLMProvider(fixed_response="It's the entry point."))
        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "main.py", "conversation_id": conversation_id},
        )

        assert response.status_code == 200
        assert response.json()["conversation_id"] == conversation_id

        detail = client.get(
            f"/api/v1/repositories/{repo.id}/conversations/{conversation_id}",
            headers=auth_headers,
        )
        roles = [m["role"] for m in detail.json()["messages"]]
        assert roles == ["user", "assistant", "user", "assistant"]


class TestExplainEndpointInsufficientEvidence:
    @pytest.mark.asyncio
    async def test_explain_nonexistent_file_returns_insufficient_evidence(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        repo = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"main.py": "def main():\n    pass\n"},
        )
        llm = MockLLMProvider()
        _override_llm(llm)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "does/not/exist.py"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "insufficient_evidence"
        assert payload["evidence"] == []
        assert llm.call_count == 0


class TestExplainEndpointRepositoryOwnership:
    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(
        self, client: TestClient, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="unauth-explain",
            full_name="testuser/unauth-explain",
            github_url="https://github.com/testuser/unauth-explain",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            json={"file_path": "main.py"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_other_user_repository_returns_404(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        other_auth_headers: dict[str, str],
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="alice-only-explain",
            full_name="testuser/alice-only-explain",
            github_url="https://github.com/testuser/alice-only-explain",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=other_auth_headers,
            json={"file_path": "main.py"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Repository not found"

    @pytest.mark.asyncio
    async def test_conversation_from_different_repository_returns_404(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        """A conversation scoped to repo A must not be usable via repo B's
        /explain endpoint, even though both are owned by the same user."""
        repo_a_dir = tmp_path / "repo_a"
        repo_b_dir = tmp_path / "repo_b"
        repo_a_dir.mkdir()
        repo_b_dir.mkdir()
        repo_a = await _make_indexed_repository(
            db_session,
            test_user,
            repo_a_dir,
            files={"a.py": "def a():\n    pass\n"},
            name="explain-repo-a-scope",
        )
        repo_b = await _make_indexed_repository(
            db_session,
            test_user,
            repo_b_dir,
            files={"b.py": "def b():\n    pass\n"},
            name="explain-repo-b-scope",
        )
        _override_llm(MockLLMProvider(fixed_response="first turn"))
        created = client.post(
            f"/api/v1/repositories/{repo_a.id}/ask",
            headers=auth_headers,
            json={"message": "a"},
        )
        conversation_id = created.json()["conversation_id"]

        response = client.post(
            f"/api/v1/repositories/{repo_b.id}/explain",
            headers=auth_headers,
            json={"file_path": "b.py", "conversation_id": conversation_id},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Conversation not found"

    @pytest.mark.asyncio
    async def test_conversation_owned_by_other_user_returns_404(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        other_user: User,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        """Bob cannot append to Alice's conversation via /explain, even if
        (hypothetically) he knew its ID -- repository ownership alone
        already blocks this since Bob does not own Alice's repository."""
        repo = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"a.py": "def a():\n    pass\n"},
        )
        _override_llm(MockLLMProvider(fixed_response="first turn"))
        created = client.post(
            f"/api/v1/repositories/{repo.id}/ask",
            headers=auth_headers,
            json={"message": "a"},
        )
        conversation_id = created.json()["conversation_id"]

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=other_auth_headers,
            json={"file_path": "a.py", "conversation_id": conversation_id},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Repository not found"

    @pytest.mark.asyncio
    async def test_repository_without_ingestion_returns_404(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="never-ingested-explain",
            full_name="testuser/never-ingested-explain",
            github_url="https://github.com/testuser/never-ingested-explain",
            status="pending",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        _override_llm(MockLLMProvider())
        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "main.py"},
        )
        assert response.status_code == 404


class TestExplainEndpointProviderFailure:
    @pytest.mark.asyncio
    async def test_llm_provider_failure_returns_502(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
    ) -> None:
        repo = await _make_indexed_repository(
            db_session,
            test_user,
            tmp_path,
            files={"svc.py": "def process():\n    pass\n"},
        )
        llm = MockLLMProvider()
        llm.raise_error = LLMProviderError("simulated 500")
        _override_llm(llm)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "svc.py", "symbol": "process"},
        )
        assert response.status_code == 502


class TestExplainEndpointValidation:
    @pytest.mark.asyncio
    async def test_end_line_before_start_line_rejected(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="val-explain",
            full_name="testuser/val-explain",
            github_url="https://github.com/testuser/val-explain",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={"file_path": "main.py", "start_line": 10, "end_line": 5},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_file_path_rejected(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="val-explain-2",
            full_name="testuser/val-explain-2",
            github_url="https://github.com/testuser/val-explain-2",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/explain",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == 422
