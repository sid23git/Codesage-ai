"""Structural candidate source for broad, repository-level questions.

For a question such as "Explain the architecture of this repository." the
best evidence is usually the root README (its introduction and its
Architecture / Features / Structure sections) and the application entry
point -- yet embedding similarity between a generic question and those
chunks is often near zero, so neither the vector nor the keyword retriever
reliably surfaces them. ``OverviewRetriever`` supplies them directly, as a
small, bounded third candidate list that ``fuse()`` scores like any other
(with an overview bonus applied only for broad questions).

Selection is purely structural and deterministic -- see
``query_analysis.is_overview_chunk``.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.rag.retrieval.query_analysis import ENTRY_POINT_FILES, is_overview_chunk

_DEFAULT_LIMIT = 8


def _overview_order(chunk: CodeChunk) -> tuple[int, str, int]:
    """README sections first (in document order), then docs, then entry points."""
    path = chunk.file_path.lower()
    base = path.rsplit("/", 1)[-1]
    if "/" not in path and base.startswith("readme"):
        rank = 0
    elif base in ENTRY_POINT_FILES:
        rank = 2
    else:
        rank = 1
    return rank, path, chunk.start_line


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def _as_vector(emb: Any) -> list[float]:
    if isinstance(emb, str):
        return [float(x) for x in json.loads(emb)]
    if hasattr(emb, "tolist"):
        return [float(x) for x in emb.tolist()]
    return [float(x) for x in emb]


class OverviewRetriever:
    """Returns README / architecture-doc / entry-point chunks for an ingestion."""

    async def search(
        self,
        db: AsyncSession,
        repository_id: int,
        ingestion_id: int,
        query_vector: list[float] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """Return up to *limit* overview chunks as ``{"chunk", "sem_score"}``.

        ``sem_score`` is the chunk's real cosine similarity to
        *query_vector* (clamped to ``[0, 1]`` exactly like
        ``VectorRetriever``), or ``0.0`` when no vector is supplied
        (keyword-only mode).
        """
        bind = await db.run_sync(lambda s: s.get_bind())
        is_postgres = bind.engine.name == "postgresql"

        path = func.lower(CodeChunk.file_path)
        entry_conds = []
        for name in ENTRY_POINT_FILES:
            entry_conds.append(path == name)
            entry_conds.append(path.like(f"%/{name}"))
        path_filter = or_(
            path.like("readme%"),
            path.like("%architecture%"),
            path.like("%overview%"),
            path.like("%design%"),
            path.like("%structure%"),
            *entry_conds,
        )

        stmt: Select[Any]
        if is_postgres and query_vector is not None:
            vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"
            stmt = select(
                CodeChunk,
                text(f"1 - (embedding <=> '{vector_str}'::vector) AS sem_score"),
            )
        else:
            stmt = select(CodeChunk)

        stmt = stmt.where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.ingestion_id == ingestion_id,
            path_filter,
        )
        rows = (await db.execute(stmt)).all()

        candidates: list[tuple[CodeChunk, float]] = []
        for row in rows:
            chunk: CodeChunk = row[0]
            if not is_overview_chunk(chunk.file_path, chunk.name, chunk.start_line):
                continue
            if query_vector is None or chunk.embedding is None:
                sem = 0.0
            elif is_postgres:
                sem = float(row[1]) if row[1] is not None else 0.0
            else:
                sem = _cosine(query_vector, _as_vector(chunk.embedding))
            candidates.append((chunk, max(0.0, min(1.0, sem))))

        candidates.sort(key=lambda t: _overview_order(t[0]))
        return [{"chunk": c, "sem_score": s} for c, s in candidates[:limit]]
