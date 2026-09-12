"""Integration tests for the Code Search RAG API endpoint."""

from __future__ import annotations

import io
import tarfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.ingestion import RepositoryIngestion
from app.models.repository import Repository
from app.models.user import User
from app.rag.embeddings.mock import MockEmbeddingProvider


def _create_tarball_bytes(files: dict[str, str]) -> bytes:
    """Create an in-memory tar.gz archive."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"repo-main/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestSearchRepositoryEndpoint:
    """Tests for POST /repositories/{repository_id}/search."""

    @pytest.mark.asyncio
    async def test_search_unauthenticated_returns_401(
        self, client: TestClient, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="public-repo",
            full_name="testuser/public-repo",
            github_url="https://github.com/testuser/public-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            json={"query": "how to login", "top_k": 5},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_search_other_user_repo_returns_404(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        other_user: User,
        other_auth_headers: dict[str, str],
    ) -> None:
        # Repository owned by test_user
        repo = Repository(
            owner_id=test_user.id,
            name="alice-repo",
            full_name="alice/alice-repo",
            github_url="https://github.com/alice/alice-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        # Bob attempts to search Alice's repository
        response = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            headers=other_auth_headers,
            json={"query": "how to login", "top_k": 5},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Repository not found"

    @pytest.mark.asyncio
    async def test_search_no_completed_ingestion_returns_404(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="unindexed-repo",
            full_name="alice/unindexed-repo",
            github_url="https://github.com/alice/unindexed-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        response = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            headers=auth_headers,
            json={"query": "how to login", "top_k": 5},
        )
        assert response.status_code == 404
        assert "No completed ingestion found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_search_success_with_ranking(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="indexed-repo",
            full_name="alice/indexed-repo",
            github_url="https://github.com/alice/indexed-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        ingestion = RepositoryIngestion(
            repository_id=repo.id,
            status="completed",
        )
        db_session.add(ingestion)
        await db_session.commit()
        await db_session.refresh(ingestion)

        provider = MockEmbeddingProvider()
        vec_jwt = await provider.embed_query("create_access_token")
        vec_other = await provider.embed_query("unrelated database migration")

        c1 = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="app/core/security.py",
            language="Python",
            chunk_type="function",
            name="create_access_token",
            start_line=15,
            end_line=30,
            content_hash="hash_sec",
            chunk_text=(
                "def create_access_token(subject: str):\n    return jwt.encode(subject)"
            ),
            embedding=vec_jwt,
        )
        c2 = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="app/db/migrate.py",
            language="Python",
            chunk_type="function",
            name="run_migrations",
            start_line=1,
            end_line=10,
            content_hash="hash_mig",
            chunk_text="def run_migrations():\n    pass",
            embedding=vec_other,
        )
        db_session.add_all([c1, c2])
        await db_session.commit()

        response = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            headers=auth_headers,
            json={
                "query": "create_access_token",
                "top_k": 2,
                "mode": "hybrid",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["query"] == "create_access_token"
        assert payload["repository_id"] == repo.id
        assert payload["ingestion_id"] == ingestion.id
        assert payload["total_results"] >= 1

        top_match = payload["results"][0]
        assert top_match["name"] == "create_access_token"
        assert top_match["file_path"] == "app/core/security.py"
        assert top_match["start_line"] == 15
        assert top_match["end_line"] == 30
        assert top_match["score"] > 0.5
        assert (
            "keyword" in top_match["retrieval_sources"]
            or "semantic" in top_match["retrieval_sources"]
        )

    @pytest.mark.asyncio
    async def test_search_repository_isolation(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        # Repo 1
        repo1 = Repository(
            owner_id=test_user.id,
            name="repo-one",
            full_name="alice/repo-one",
            github_url="https://github.com/alice/repo-one",
            status="ready",
        )
        # Repo 2
        repo2 = Repository(
            owner_id=test_user.id,
            name="repo-two",
            full_name="alice/repo-two",
            github_url="https://github.com/alice/repo-two",
            status="ready",
        )
        db_session.add_all([repo1, repo2])
        await db_session.commit()
        await db_session.refresh(repo1)
        await db_session.refresh(repo2)

        ing1 = RepositoryIngestion(repository_id=repo1.id, status="completed")
        ing2 = RepositoryIngestion(repository_id=repo2.id, status="completed")
        db_session.add_all([ing1, ing2])
        await db_session.commit()
        await db_session.refresh(ing1)
        await db_session.refresh(ing2)

        provider = MockEmbeddingProvider()
        vec = await provider.embed_query("target_secret_token")

        c1 = CodeChunk(
            repository_id=repo1.id,
            ingestion_id=ing1.id,
            file_path="repo1_file.py",
            language="Python",
            chunk_type="function",
            name="repo1_func",
            start_line=1,
            end_line=5,
            content_hash="h1",
            chunk_text="def repo1_func(): pass",
            embedding=vec,
        )
        c2 = CodeChunk(
            repository_id=repo2.id,
            ingestion_id=ing2.id,
            file_path="repo2_file.py",
            language="Python",
            chunk_type="function",
            name="repo2_secret_function",
            start_line=1,
            end_line=5,
            content_hash="h2",
            chunk_text="def repo2_secret_function(): pass",
            embedding=vec,
        )
        db_session.add_all([c1, c2])
        await db_session.commit()

        # Search Repo 1 only
        response = client.post(
            f"/api/v1/repositories/{repo1.id}/search",
            headers=auth_headers,
            json={"query": "target_secret_token", "top_k": 10},
        )
        assert response.status_code == 200
        results = response.json()["results"]

        # Chunks from Repo 2 MUST NOT appear
        returned_paths = [r["file_path"] for r in results]
        assert "repo1_file.py" in returned_paths
        assert "repo2_file.py" not in returned_paths

    @pytest.mark.asyncio
    async def test_search_input_validation(
        self,
        client: TestClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="val-repo",
            full_name="alice/val-repo",
            github_url="https://github.com/alice/val-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()

        # Empty query
        res_empty = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            headers=auth_headers,
            json={"query": "", "top_k": 5},
        )
        assert res_empty.status_code == 422

        # top_k > 50
        res_large_k = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            headers=auth_headers,
            json={"query": "valid query", "top_k": 100},
        )
        assert res_large_k.status_code == 422

        # top_k < 1
        res_zero_k = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            headers=auth_headers,
            json={"query": "valid query", "top_k": 0},
        )
        assert res_zero_k.status_code == 422

        # query too long (> 1000)
        res_long_q = client.post(
            f"/api/v1/repositories/{repo.id}/search",
            headers=auth_headers,
            json={"query": "a" * 1001, "top_k": 5},
        )
        assert res_long_q.status_code == 422
