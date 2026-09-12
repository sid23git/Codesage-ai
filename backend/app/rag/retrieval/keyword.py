"""Keyword and exact-symbol retriever using PostgreSQL Full-Text Search."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Select, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk

logger = logging.getLogger(__name__)


class KeywordRetriever:
    """Performs lexical retrieval using PostgreSQL FTS and exact symbol matching."""

    async def search(
        self,
        db: AsyncSession,
        query: str,
        repository_id: int,
        ingestion_id: int,
        top_k: int,
        file_extensions: list[str] | None = None,
        file_paths: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return chunks that match *query* by FTS rank or exact symbol name.

        Parameters
        ----------
        db:
            Async database session.
        query:
            Raw search query string.
        repository_id:
            Repository PK — enforces ownership isolation.
        ingestion_id:
            Only chunks from this ingestion are considered.
        top_k:
            Maximum candidates to return.
        file_extensions:
            Optional whitelist of file extensions.
        file_paths:
            Optional path prefix filters.

        Returns
        -------
        list[dict]
            Each dict contains the chunk ORM fields plus ``lex_score``
            normalised to ``[0.0, 1.0]``.
        """
        # Build safe FTS expression using plainto_tsquery (no tsvector column
        # exposed on SQLite; keyword retrieval is silently empty on SQLite).
        # We handle the case where the DB has no tsvector column (tests use SQLite).
        bind = await db.run_sync(lambda s: s.get_bind())
        is_postgres = bind.engine.name == "postgresql"

        stmt: Select[Any]

        if is_postgres:
            ts_rank_expr = text(
                "ts_rank_cd(tsv_content, plainto_tsquery('english', :q)) AS lex_score"
            )
            exact_name_cond = text("LOWER(name) = LOWER(:q)")
            fts_cond = text("tsv_content @@ plainto_tsquery('english', :q)")

            stmt = (
                select(
                    CodeChunk,
                    ts_rank_expr,
                )
                .where(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.ingestion_id == ingestion_id,
                    or_(fts_cond, exact_name_cond),
                )
                .order_by(text("lex_score DESC"))
                .limit(top_k)
                .params(q=query)
            )
        else:
            # SQLite fallback: simple LIKE match for unit tests
            like_q = f"%{query}%"
            stmt = (
                select(CodeChunk)
                .where(
                    CodeChunk.repository_id == repository_id,
                    CodeChunk.ingestion_id == ingestion_id,
                    or_(
                        CodeChunk.chunk_text.ilike(like_q),
                        CodeChunk.name.ilike(like_q),
                    ),
                )
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

        results: list[dict[str, Any]] = []
        for row in rows:
            if is_postgres:
                chunk: CodeChunk = row[0]
                raw_lex: float = float(row[1]) if row[1] is not None else 0.0
            else:
                chunk = row[0]
                raw_lex = 0.5  # SQLite fallback: flat score for any match

            # Normalise ts_rank_cd to [0, 1] with a soft cap at 0.5
            lex_score = min(1.0, raw_lex / 0.5) if is_postgres else raw_lex

            results.append(
                {
                    "chunk": chunk,
                    "lex_score": max(0.0, min(1.0, lex_score)),
                }
            )

        return results
