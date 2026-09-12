"""Tests for vector storage, ORM models, and re-indexing lifecycle."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.ingestion import RepositoryIngestion
from app.models.repository import Repository
from app.models.user import User
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.services.rag_service import RAGService


class TestCodeChunkStorage:
    """Test CodeChunk persistence and lifecycle."""

    @pytest.mark.asyncio
    async def test_create_and_query_code_chunk(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="test-repo",
            full_name="testuser/test-repo",
            github_url="https://github.com/testuser/test-repo",
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

        chunk = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="src/main.py",
            language="Python",
            chunk_type="function",
            name="main",
            start_line=1,
            end_line=10,
            content_hash="abc123hash",
            chunk_text="def main():\n    pass",
            embedding=[0.0] * 1536,
        )
        db_session.add(chunk)
        await db_session.commit()
        await db_session.refresh(chunk)

        assert chunk.id is not None
        assert chunk.file_path == "src/main.py"
        assert chunk.name == "main"
        assert chunk.repository.id == repo.id
        assert chunk.ingestion.id == ingestion.id

    @pytest.mark.asyncio
    async def test_cascade_delete_repository_deletes_chunks(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="delete-repo",
            full_name="testuser/delete-repo",
            github_url="https://github.com/testuser/delete-repo",
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

        chunk = CodeChunk(
            repository_id=repo.id,
            ingestion_id=ingestion.id,
            file_path="src/main.py",
            language="Python",
            chunk_type="function",
            name="main",
            start_line=1,
            end_line=5,
            content_hash="hash1",
            chunk_text="def main(): pass",
            embedding=[0.0] * 1536,
        )
        db_session.add(chunk)
        await db_session.commit()

        from app.services.repository_service import RepositoryService

        # Capture plain identifiers before expiring anything below. Reading an
        # attribute off an expired ORM instance outside of an awaited call
        # triggers a synchronous reload attempt, which raises MissingGreenlet
        # under AsyncSession — so nothing ORM-backed is touched after this.
        owner_id = test_user.id
        repository_id = repo.id

        # Expire only `repo` so its code_chunks/ingestions are re-queried with
        # latest children. Using expire_all() here would also expire unrelated
        # fixture objects (e.g. test_user).
        db_session.expire(repo)

        # Delete repository through service
        deleted = await RepositoryService.delete_repository(
            db_session, owner_id, repository_id
        )
        assert deleted is True
        await db_session.commit()

        # Verify chunk is gone
        result = await db_session.execute(
            select(CodeChunk).where(CodeChunk.repository_id == repository_id)
        )
        assert len(result.scalars().all()) == 0

    @pytest.mark.asyncio
    async def test_reindexing_cleans_up_stale_chunks(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = Repository(
            owner_id=test_user.id,
            name="reindex-repo",
            full_name="testuser/reindex-repo",
            github_url="https://github.com/testuser/reindex-repo",
            status="ready",
        )
        db_session.add(repo)
        await db_session.commit()
        await db_session.refresh(repo)

        provider = MockEmbeddingProvider()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            f1 = temp_path / "app.py"
            f1.write_text("def v1_func(): pass\n", encoding="utf-8")

            # First ingestion
            ing1 = RepositoryIngestion(repository_id=repo.id, status="completed")
            db_session.add(ing1)
            await db_session.commit()
            await db_session.refresh(ing1)

            count1 = await RAGService.index_repository(
                db=db_session,
                repository_id=repo.id,
                ingestion_id=ing1.id,
                source_root=temp_path,
                embedding_provider=provider,
            )
            assert count1 >= 1

            # Second ingestion with updated file
            f1.write_text("def v2_func(): pass\ndef helper(): pass\n", encoding="utf-8")
            ing2 = RepositoryIngestion(repository_id=repo.id, status="completed")
            db_session.add(ing2)
            await db_session.commit()
            await db_session.refresh(ing2)

            count2 = await RAGService.index_repository(
                db=db_session,
                repository_id=repo.id,
                ingestion_id=ing2.id,
                source_root=temp_path,
                embedding_provider=provider,
            )
            assert count2 >= 2

            # Verify no chunks remain from ingestion 1
            chunks_ing1 = (
                (
                    await db_session.execute(
                        select(CodeChunk).where(CodeChunk.ingestion_id == ing1.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(chunks_ing1) == 0

            # Verify chunks from ingestion 2 exist
            chunks_ing2 = (
                (
                    await db_session.execute(
                        select(CodeChunk).where(CodeChunk.ingestion_id == ing2.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(chunks_ing2) == count2
