"""Real Voyage AI integration tests.

These make genuine network calls to Voyage's API and are skipped entirely
unless the operator has supplied a real ``VOYAGE_API_KEY`` in their own
local environment -- never in CI, never with a fabricated/test key. The
key is read only from the environment and is never printed or logged by
these tests.

The retrieval-quality test additionally requires ``TEST_DATABASE_URL``
(a real Postgres+pgvector instance -- see conftest.py's module docstring)
since it inserts real 1024-dim embeddings into the pgvector column and
exercises the real ``<=>`` operator via VectorRetriever.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.ingestion import RepositoryIngestion
from app.models.repository import Repository
from app.models.user import User
from app.rag.embeddings.voyage import VoyageEmbeddingProvider
from app.rag.retrieval.vector import VectorRetriever

pytestmark = pytest.mark.skipif(
    not os.environ.get("VOYAGE_API_KEY"),
    reason=(
        "Requires a real VOYAGE_API_KEY supplied locally by the operator "
        "(never set in CI) -- see this file's module docstring."
    ),
)


def _provider() -> VoyageEmbeddingProvider:
    api_key = os.environ["VOYAGE_API_KEY"]
    return VoyageEmbeddingProvider(api_key=api_key)


class TestVoyageRealEmbeddings:
    """Basic real-API shape checks -- no database required."""

    @pytest.mark.asyncio
    async def test_embed_texts_returns_1024_dimensional_vectors(self) -> None:
        provider = _provider()
        vectors = await provider.embed_texts(
            ["def authenticate_user(email: str, password: str) -> User: ..."]
        )
        assert len(vectors) == 1
        assert len(vectors[0]) == 1024
        assert all(isinstance(v, float) for v in vectors[0])

    @pytest.mark.asyncio
    async def test_embed_query_returns_1024_dimensional_vector(self) -> None:
        provider = _provider()
        vector = await provider.embed_query("how does authentication work?")
        assert len(vector) == 1024

    @pytest.mark.asyncio
    async def test_document_and_query_input_types_produce_different_vectors(
        self,
    ) -> None:
        """Proves input_type is actually threaded through to Voyage, not
        defaulted/ignored -- the same string embedded as a document vs. as
        a query must not produce an identical vector, since Voyage
        prepends a different instruction prefix for each."""
        provider = _provider()
        text = "user authentication and session management"

        document_vector = (await provider.embed_texts([text]))[0]
        query_vector = await provider.embed_query(text)

        assert document_vector != query_vector


class TestVoyageRealRetrievalQuality:
    """Insert real Voyage embeddings into real Postgres and verify semantic
    ranking -- requires both VOYAGE_API_KEY and TEST_DATABASE_URL."""

    pytestmark = pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason=(
            "Requires TEST_DATABASE_URL (a real Postgres+pgvector instance) "
            "in addition to VOYAGE_API_KEY -- inserts real 1024-dim vectors "
            "into the pgvector column."
        ),
    )

    @pytest.mark.asyncio
    async def test_semantically_related_chunk_outranks_unrelated_chunk(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="voyage-retrieval-repo",
            full_name="testuser/voyage-retrieval-repo",
            github_url="https://github.com/testuser/voyage-retrieval-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        ingestion = RepositoryIngestion(repository_id=repo.id, status="completed")
        db_session.add(ingestion)
        await db_session.commit()
        await db_session.refresh(ingestion)

        provider = _provider()

        auth_code = (
            "def verify_password(plain_password: str, hashed_password: str) -> bool:\n"
            "    return bcrypt.checkpw(\n"
            "        plain_password.encode(), hashed_password.encode()\n"
            "    )"
        )
        unrelated_code = (
            "def parse_csv_row(row: str) -> list[str]:\n"
            "    return [cell.strip() for cell in row.split(',')]"
        )

        vectors = await provider.embed_texts([auth_code, unrelated_code])

        auth_chunk = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="app/auth.py",
            language="Python",
            chunk_type="function",
            name="verify_password",
            start_line=1,
            end_line=2,
            content_hash="h1",
            chunk_text=auth_code,
            embedding=vectors[0],
        )
        unrelated_chunk = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="app/csv_utils.py",
            language="Python",
            chunk_type="function",
            name="parse_csv_row",
            start_line=1,
            end_line=2,
            content_hash="h2",
            chunk_text=unrelated_code,
            embedding=vectors[1],
        )
        db_session.add_all([auth_chunk, unrelated_chunk])
        await db_session.commit()

        query_vector = await provider.embed_query(
            "how do I check a user's password against a stored hash?"
        )

        results = await VectorRetriever().search(
            db=db_session,
            query_vector=query_vector,
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            top_k=2,
        )

        assert len(results) == 2
        assert results[0]["chunk"].id == auth_chunk.id, (
            "Expected the password-verification chunk to rank above the "
            "unrelated CSV-parsing chunk for an authentication-related "
            "query -- real Voyage embeddings should separate these clearly."
        )
        assert results[0]["sem_score"] > results[1]["sem_score"]
