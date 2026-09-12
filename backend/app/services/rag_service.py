"""RAG service: orchestrates chunking, embedding, persistence, and retrieval.

Design principles
-----------------
- Phase 1 (chunking) and Phase 2 (external embedding calls) run OUTSIDE any
  database transaction to prevent holding open connections across network I/O.
- Phase 3 (bulk persistence) is a single bounded ACID transaction.
- Repository/ingestion isolation is enforced at every query level.
- Stale chunks from previous ingestions of the same repository are deleted
  atomically inside Phase 3 after new chunks are confirmed written.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.ingestion import RepositoryIngestion
from app.rag.chunking import RawChunk, chunk_file
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.retrieval.hybrid import fuse
from app.rag.retrieval.keyword import KeywordRetriever
from app.rag.retrieval.vector import VectorRetriever
from app.schemas.rag import ChunkSearchResult, CodeSearchRequest, RetrievalMode

logger = logging.getLogger(__name__)

_EMBEDDING_BATCH_SIZE = 64


class RAGService:
    """High-level service for RAG indexing and retrieval."""

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    @classmethod
    async def index_repository(
        cls,
        db: AsyncSession,
        repository_id: int,
        ingestion_id: int,
        source_root: Path,
        embedding_provider: BaseEmbeddingProvider,
    ) -> int:
        """Chunk, embed, and persist all source files from *source_root*.

        Transaction boundary
        --------------------
        This method is intentionally structured so that **no database
        transaction is held open while making external embedding API calls**.

        1. Walk source tree and generate ``RawChunk`` objects (no DB).
        2. Batch-generate embeddings via the provider (no DB).
        3. Open a single bounded transaction to bulk-insert chunks and
           delete any stale chunks from prior completed ingestions.

        Parameters
        ----------
        db:
            Async database session (transaction managed here).
        repository_id:
            PK of the parent repository (for isolation).
        ingestion_id:
            PK of the current ingestion run.
        source_root:
            Root directory of the extracted repository archive.
        embedding_provider:
            Configured embedding provider (mock for tests, OpenAI for production).

        Returns
        -------
        int
            Number of chunks successfully persisted.

        Raises
        ------
        RuntimeError
            If embedding generation fails unrecoverably.
        """
        # ── Phase 1: Collect all chunks (no DB open) ──────────────────
        raw_chunks = cls._collect_chunks(source_root)

        if not raw_chunks:
            logger.info(
                "No chunks produced for ingestion_id=%s — skipping indexing.",
                ingestion_id,
            )
            return 0

        logger.info(
            "Collected %d chunks for ingestion_id=%s; generating embeddings.",
            len(raw_chunks),
            ingestion_id,
        )

        # ── Phase 2: Batch embedding generation (no DB open) ──────────
        texts = [c.chunk_text for c in raw_chunks]
        all_vectors: list[list[float]] = []

        for batch_start in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[batch_start : batch_start + _EMBEDDING_BATCH_SIZE]
            batch_vectors = await embedding_provider.embed_texts(batch)
            all_vectors.extend(batch_vectors)

        logger.info(
            "Embeddings generated (%d total) for ingestion_id=%s.",
            len(all_vectors),
            ingestion_id,
        )

        # ── Phase 3: Bounded DB transaction ───────────────────────────
        rows: list[CodeChunk] = []
        for chunk, vector in zip(raw_chunks, all_vectors, strict=True):
            rows.append(
                CodeChunk(
                    repository_id=repository_id,
                    ingestion_id=ingestion_id,
                    file_path=chunk.file_path,
                    language=chunk.language,
                    chunk_type=chunk.chunk_type,
                    name=chunk.name,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content_hash=chunk.content_hash,
                    chunk_text=chunk.chunk_text,
                    embedding=vector,
                )
            )

        # Guarantee this persist step is a single, short, self-contained
        # transaction: if the caller left an ambient transaction open (e.g.
        # from a prior refresh()/read), close it out first so nothing
        # unrelated gets swept into this commit and the transaction below is
        # bounded strictly to the insert + stale-chunk cleanup.
        if db.in_transaction():
            await db.commit()

        async with db.begin():
            # Insert new chunks
            db.add_all(rows)
            await db.flush()

            # Delete stale chunks from any prior completed ingestion of this repo
            await db.execute(
                delete(CodeChunk).where(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.ingestion_id != ingestion_id,
                )
            )
        # `async with db.begin()` commits automatically on clean exit here.

        logger.info(
            "Persisted %d code chunks for ingestion_id=%s (stale chunks removed).",
            len(rows),
            ingestion_id,
        )
        return len(rows)

    @classmethod
    def _collect_chunks(cls, source_root: Path) -> list[RawChunk]:
        """Walk *source_root* and produce RawChunks for all readable text files."""
        from app.ingestion.languages import detect_language

        chunks: list[RawChunk] = []

        for file_path in sorted(source_root.rglob("*")):
            if not file_path.is_file():
                continue

            rel_path = file_path.relative_to(source_root).as_posix()
            language = detect_language(file_path)

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("Skipping unreadable file %s: %s", rel_path, exc)
                continue

            if not text.strip():
                continue

            file_chunks = chunk_file(
                file_path=rel_path,
                language=language,
                text=text,
            )
            chunks.extend(file_chunks)

        return chunks

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    @classmethod
    async def search(
        cls,
        db: AsyncSession,
        request: CodeSearchRequest,
        repository_id: int,
        owner_id: int,
        embedding_provider: BaseEmbeddingProvider,
    ) -> tuple[list[ChunkSearchResult], int]:
        """Execute a hybrid code search for an owned repository.

        Parameters
        ----------
        db:
            Async database session.
        request:
            Validated ``CodeSearchRequest`` payload.
        repository_id:
            Repository PK — ownership verified before this is called.
        owner_id:
            User PK (used to resolve the latest completed ingestion).
        embedding_provider:
            Embedding provider instance for query vectorisation.

        Returns
        -------
        tuple[list[ChunkSearchResult], int]
            ``(ranked_results, ingestion_id)``

        Raises
        ------
        ValueError
            If the repository has no completed ingestion.
        """
        ingestion_id = await cls._resolve_latest_completed_ingestion(db, repository_id)
        if ingestion_id is None:
            raise ValueError(
                "No completed ingestion found for this repository. "
                "Run POST /repositories/{id}/ingest first."
            )

        sem_results: list[dict[str, Any]] = []
        lex_results: list[dict[str, Any]] = []

        top_k_candidates = request.top_k * 2

        if request.mode in (RetrievalMode.HYBRID, RetrievalMode.SEMANTIC):
            query_vector = await embedding_provider.embed_query(request.query)
            sem_results = await VectorRetriever().search(
                db=db,
                query_vector=query_vector,
                repository_id=repository_id,
                ingestion_id=ingestion_id,
                top_k=top_k_candidates,
                file_extensions=request.file_extensions,
                file_paths=request.file_paths,
            )

        if request.mode in (RetrievalMode.HYBRID, RetrievalMode.KEYWORD):
            lex_results = await KeywordRetriever().search(
                db=db,
                query=request.query,
                repository_id=repository_id,
                ingestion_id=ingestion_id,
                top_k=top_k_candidates,
                file_extensions=request.file_extensions,
                file_paths=request.file_paths,
            )

        results = fuse(
            sem_results=sem_results,
            lex_results=lex_results,
            query=request.query,
            top_k=request.top_k,
            min_score=request.min_score,
        )

        return results, ingestion_id

    @classmethod
    async def _resolve_latest_completed_ingestion(
        cls, db: AsyncSession, repository_id: int
    ) -> int | None:
        """Return the PK of the most recent completed ingestion, or None."""
        result = await db.execute(
            select(RepositoryIngestion.id)
            .where(
                RepositoryIngestion.repository_id == repository_id,
                RepositoryIngestion.status == "completed",
            )
            .order_by(
                RepositoryIngestion.created_at.desc(), RepositoryIngestion.id.desc()
            )
            .limit(1)
        )
        row = result.scalars().first()
        return int(row) if row is not None else None
