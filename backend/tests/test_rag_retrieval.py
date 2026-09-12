"""Tests for vector, keyword, and hybrid Linear Score Fusion retrieval."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.ingestion import RepositoryIngestion
from app.models.repository import Repository
from app.models.user import User
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.rag.retrieval.hybrid import _compute_score, fuse
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.vector import VectorRetriever


class TestLinearScoreFusion:
    """Test the Linear Score Fusion formula and ranking."""

    def test_compute_score_formula(self) -> None:
        chunk = CodeChunk(
            id=1,
            repository_id=1,
            ingestion_id=1,
            file_path="app/core/security.py",
            name="create_access_token",
            start_line=1,
            end_line=10,
            content_hash="h1",
            chunk_text="def create_access_token(): pass",
        )

        # Exact symbol match query
        score, sources = _compute_score(
            sem_score=0.8,
            lex_score=0.5,
            query_lower="create_access_token",
            chunk=chunk,
        )

        # Expected: 0.70*0.8 + 0.30*0.5 + 0.20 (symbol) + 0.0 (path) = 0.91
        assert pytest.approx(score, rel=1e-3) == 0.91
        assert "semantic" in sources
        assert "keyword" in sources

    def test_compute_score_path_bonus(self) -> None:
        chunk = CodeChunk(
            id=2,
            repository_id=1,
            ingestion_id=1,
            file_path="app/services/auth_service.py",
            name="authenticate_user",
            start_line=1,
            end_line=10,
            content_hash="h2",
            chunk_text="def authenticate_user(): pass",
        )

        score, sources = _compute_score(
            sem_score=0.5,
            lex_score=0.0,
            query_lower="how auth works",
            chunk=chunk,
        )

        # Expected: 0.70 * 0.5 (0.35) + 0.0 + 0.0 + 0.10 (path contains 'auth') = 0.45
        assert pytest.approx(score, rel=1e-3) == 0.45
        assert sources == ["semantic"]

    def test_fuse_deduplicates_and_orders(self) -> None:
        c1 = CodeChunk(
            id=1,
            repository_id=1,
            ingestion_id=1,
            file_path="a.py",
            name="fn_a",
            start_line=1,
            end_line=5,
            content_hash="h1",
            chunk_text="code a",
        )
        c2 = CodeChunk(
            id=2,
            repository_id=1,
            ingestion_id=1,
            file_path="b.py",
            name="fn_b",
            start_line=1,
            end_line=5,
            content_hash="h2",
            chunk_text="code b",
        )

        sem_results = [{"chunk": c1, "sem_score": 0.9}, {"chunk": c2, "sem_score": 0.4}]
        lex_results = [{"chunk": c2, "lex_score": 0.8}]

        results = fuse(
            sem_results=sem_results,
            lex_results=lex_results,
            query="search query",
            top_k=5,
        )

        assert len(results) == 2
        # c1 has 0.70 * 0.9 = 0.63
        # c2 has 0.70 * 0.4 + 0.30 * 0.8 = 0.28 + 0.24 = 0.52
        assert results[0].chunk_id == 1
        assert results[1].chunk_id == 2


class TestRetrievers:
    """Test VectorRetriever and KeywordRetriever."""

    @pytest.mark.asyncio
    async def test_vector_and_keyword_retrievers(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="retrieval-repo",
            full_name="testuser/retrieval-repo",
            github_url="https://github.com/testuser/retrieval-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        ingestion = RepositoryIngestion(repository_id=repo.id, status="completed")
        db_session.add(ingestion)
        await db_session.commit()
        await db_session.refresh(ingestion)

        provider = MockEmbeddingProvider()
        vec_auth = await provider.embed_query("authentication tokens")
        vec_db = await provider.embed_query("database pool connections")

        c1 = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="app/auth.py",
            language="Python",
            chunk_type="function",
            name="verify_token",
            start_line=1,
            end_line=10,
            content_hash="h1",
            chunk_text="def verify_token(token: str): pass",
            embedding=vec_auth,
        )
        c2 = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="app/db.py",
            language="Python",
            chunk_type="function",
            name="get_connection",
            start_line=1,
            end_line=10,
            content_hash="h2",
            chunk_text="def get_connection(): pass",
            embedding=vec_db,
        )
        db_session.add_all([c1, c2])
        await db_session.commit()

        # Test Vector Search
        vector_retriever = VectorRetriever()
        sem_res = await vector_retriever.search(
            db=db_session,
            query_vector=vec_auth,
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            top_k=2,
        )
        assert len(sem_res) == 2
        assert sem_res[0]["chunk"].id == c1.id
        assert pytest.approx(sem_res[0]["sem_score"], rel=1e-4) == 1.0

        # Test Keyword Search
        keyword_retriever = KeywordRetriever()
        lex_res = await keyword_retriever.search(
            db=db_session,
            query="verify_token",
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            top_k=2,
        )
        assert len(lex_res) >= 1
        assert lex_res[0]["chunk"].id == c1.id
