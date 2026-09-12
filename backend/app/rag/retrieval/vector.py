"""Dense vector retriever using PostgreSQL + pgvector."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk

logger = logging.getLogger(__name__)


class VectorRetriever:
    """Performs ANN cosine-similarity retrieval against pgvector."""

    async def search(
        self,
        db: AsyncSession,
        query_vector: list[float],
        repository_id: int,
        ingestion_id: int,
        top_k: int,
        file_extensions: list[str] | None = None,
        file_paths: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the closest chunks to *query_vector* within a single ingestion.

        Parameters
        ----------
        db:
            Async database session.
        query_vector:
            1536-dimensional embedding of the search query.
        repository_id:
            Repository PK — enforces ownership isolation.
        ingestion_id:
            Only chunks from this ingestion are considered.
        top_k:
            Maximum candidates to return (before hybrid fusion).
        file_extensions:
            Optional whitelist of file extensions (e.g. ``[".py"]``).
        file_paths:
            Optional path prefix filters.

        Returns
        -------
        list[dict]
            Each dict contains the chunk ORM fields plus ``sem_score`` in
            ``[0.0, 1.0]`` (1 - cosine distance).
        """
        from sqlalchemy import or_

        bind = await db.run_sync(lambda s: s.get_bind())
        is_postgres = bind.engine.name == "postgresql"

        results: list[dict[str, Any]] = []

        stmt: Select[Any]

        if is_postgres:
            # Build the parameterised vector literal as a cast so asyncpg
            # handles it cleanly.
            vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

            # Base query using pgvector <=> operator (cosine distance)
            stmt = (
                select(
                    CodeChunk,
                    text(f"1 - (embedding <=> '{vector_str}'::vector) AS sem_score"),
                )
                .where(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.ingestion_id == ingestion_id,
                    CodeChunk.embedding.is_not(None),
                )
                .order_by(text(f"embedding <=> '{vector_str}'::vector"))
                .limit(top_k)
            )

            # Optional file-extension filter
            if file_extensions:
                conditions = [
                    CodeChunk.file_path.like(f"%{ext}") for ext in file_extensions
                ]
                stmt = stmt.where(or_(*conditions))

            # Optional file-path prefix filter
            if file_paths:
                path_conditions = [
                    CodeChunk.file_path.like(f"{prefix}%") for prefix in file_paths
                ]
                stmt = stmt.where(or_(*path_conditions))

            rows = (await db.execute(stmt)).all()

            for row in rows:
                chunk: CodeChunk = row[0]
                sem_score: float = float(row[1]) if row[1] is not None else 0.0
                results.append(
                    {
                        "chunk": chunk,
                        "sem_score": max(0.0, min(1.0, sem_score)),
                    }
                )
        else:
            # SQLite fallback (used during in-memory automated tests)
            stmt = select(CodeChunk).where(
                CodeChunk.repository_id == repository_id,
                CodeChunk.ingestion_id == ingestion_id,
                CodeChunk.embedding.is_not(None),
            )

            if file_extensions:
                conditions = [
                    CodeChunk.file_path.like(f"%{ext}") for ext in file_extensions
                ]
                stmt = stmt.where(or_(*conditions))

            if file_paths:
                path_conditions = [
                    CodeChunk.file_path.like(f"{prefix}%") for prefix in file_paths
                ]
                stmt = stmt.where(or_(*path_conditions))

            chunks = (await db.execute(stmt)).scalars().all()
            scored: list[tuple[CodeChunk, float]] = []

            for chunk in chunks:
                emb = chunk.embedding
                if emb is None:
                    continue
                if isinstance(emb, str):
                    try:
                        import json

                        emb_vec = json.loads(emb)
                    except Exception:
                        emb_vec = [
                            float(x.strip())
                            for x in emb.strip("[]").split(",")
                            if x.strip()
                        ]
                elif hasattr(emb, "tolist"):
                    emb_vec = emb.tolist()
                elif isinstance(emb, (list, tuple)):
                    emb_vec = list(emb)
                else:
                    emb_vec = list(emb)

                dot_prod = sum(
                    a * b for a, b in zip(query_vector, emb_vec, strict=True)
                )
                norm_q = sum(a * a for a in query_vector) ** 0.5
                norm_e = sum(b * b for b in emb_vec) ** 0.5
                if norm_q > 0 and norm_e > 0:
                    sim = dot_prod / (norm_q * norm_e)
                else:
                    sim = 0.0

                score = max(0.0, min(1.0, sim))
                scored.append((chunk, score))

            scored.sort(key=lambda x: x[1], reverse=True)
            for chunk, score in scored[:top_k]:
                results.append({"chunk": chunk, "sem_score": score})

        return results
