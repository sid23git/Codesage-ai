"""Keyword and exact-symbol retriever using PostgreSQL Full-Text Search.

Matching strategy
-----------------
The query is reduced to its content-bearing terms (``lexical_terms``:
stopwords and question scaffolding removed, identifiers/paths kept whole).
Each term becomes its own ``plainto_tsquery('english', term)`` -- so
stemming and PostgreSQL's parser apply exactly as they did when
``tsv_content`` was built, and a multi-part identifier such as
``verify_token`` still requires *all* of its parts -- and the terms are
OR-ed together. A chunk therefore matches when it contains *any* content
term, instead of the previous ``plainto_tsquery(<whole question>)`` which
AND-ed every word and so almost never matched a natural-language question.

Scoring
-------
``lex_score`` is IDF-weighted term coverage:

    lex_score(c) = sum(w(t) for t matched by c) / sum(w(t) for t in Q)
    w(t)         = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

where ``N`` is the number of chunks in the ingestion and ``df(t)`` the
number containing ``t``. A term present in *no* chunk stays in the
denominator at its maximum weight ``w(df=0)``: if the question's specific
vocabulary ("stripe payment refunds") does not exist in the repository, a
chunk that merely matches one leftover generic term ("processed") must not
look like full coverage. (Terms PostgreSQL itself treats as stopwords --
an empty ``plainto_tsquery`` -- are ignored entirely.) Matching a rare,
specific term counts for more than matching one that appears everywhere, and
a chunk containing every content term scores 1.0. An exact
(case-insensitive) symbol-name match of the whole query always scores 1.0
and ranks first.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from sqlalchemy import Select, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.rag.retrieval.query_analysis import lexical_terms

logger = logging.getLogger(__name__)


def idf_weight(df: int, n: int) -> float:
    """BM25-style inverse document frequency (always > 0 for ``0 <= df <= n``)."""
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))


def weighted_coverage(matched: list[bool], weights: list[float]) -> float:
    """Fraction of total term weight matched, in ``[0, 1]``."""
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(w for m, w in zip(matched, weights, strict=True) if m) / total


def _apply_filters(
    stmt: Select[Any],
    file_extensions: list[str] | None,
    file_paths: list[str] | None,
) -> Select[Any]:
    if file_extensions:
        stmt = stmt.where(
            or_(*[CodeChunk.file_path.like(f"%{ext}") for ext in file_extensions])
        )
    if file_paths:
        stmt = stmt.where(
            or_(*[CodeChunk.file_path.like(f"{prefix}%") for prefix in file_paths])
        )
    return stmt


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
        """Return chunks that match *query* by FTS term coverage or exact symbol name.

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
        bind = await db.run_sync(lambda s: s.get_bind())
        terms = lexical_terms(query)

        if bind.engine.name == "postgresql":
            return await self._search_postgres(
                db,
                query,
                terms,
                repository_id,
                ingestion_id,
                top_k,
                file_extensions,
                file_paths,
            )
        return await self._search_fallback(
            db,
            query,
            terms,
            repository_id,
            ingestion_id,
            top_k,
            file_extensions,
            file_paths,
        )

    # ------------------------------------------------------------------
    # PostgreSQL: real FTS against the ``tsv_content`` generated column
    # ------------------------------------------------------------------

    async def _search_postgres(
        self,
        db: AsyncSession,
        query: str,
        terms: list[str],
        repository_id: int,
        ingestion_id: int,
        top_k: int,
        file_extensions: list[str] | None,
        file_paths: list[str] | None,
    ) -> list[dict[str, Any]]:
        term_params = {f"t{i}": term for i, term in enumerate(terms)}
        term_match = [
            f"(tsv_content @@ plainto_tsquery('english', :t{i}))"
            for i in range(len(terms))
        ]

        # Document frequencies of each term within this ingestion (one pass).
        weights: list[float] = []
        usable: list[int] = []
        absent_weight = 0.0
        if terms:
            df_cols = ", ".join(
                f"count(*) FILTER (WHERE {cond}) AS df{i}, "
                f"numnode(plainto_tsquery('english', :t{i})) AS nn{i}"
                for i, cond in enumerate(term_match)
            )
            df_row = (
                await db.execute(
                    text(
                        f"SELECT count(*) AS n, {df_cols} FROM code_chunks "  # noqa: S608 -- only generated placeholders are interpolated
                        "WHERE repository_id = :repository_id "
                        "AND ingestion_id = :ingestion_id"
                    ),
                    {
                        "repository_id": repository_id,
                        "ingestion_id": ingestion_id,
                        **term_params,
                    },
                )
            ).one()
            n = int(df_row[0])
            for i in range(len(terms)):
                df = int(df_row[1 + 2 * i])
                if int(df_row[2 + 2 * i]) == 0:
                    continue  # a PostgreSQL stopword: no lexemes to match
                if df > 0:
                    usable.append(i)
                    weights.append(idf_weight(df, n))
                else:
                    absent_weight += idf_weight(0, n)

        exact_name = "(LOWER(name) = LOWER(:q))"
        if usable:
            total = sum(weights) + absent_weight
            weighted = " + ".join(
                f"(CASE WHEN {term_match[i]} THEN {w / total!r} ELSE 0.0 END)"
                for i, w in zip(usable, weights, strict=True)
            )
            any_term = " OR ".join(term_match[i] for i in usable)
            lex_expr = f"(CASE WHEN {exact_name} THEN 1.0 ELSE ({weighted}) END)"
            # Fully parenthesised: text() is spliced into the WHERE clause
            # verbatim, and a bare OR would bind looser than the
            # repository/ingestion/path conditions AND-ed around it.
            match_cond = f"(({any_term}) OR {exact_name})"
        else:
            lex_expr = f"(CASE WHEN {exact_name} THEN 1.0 ELSE 0.0 END)"
            match_cond = exact_name

        stmt: Select[Any] = (
            select(CodeChunk, text(f"{lex_expr} AS lex_score"))
            .where(
                CodeChunk.repository_id == repository_id,
                CodeChunk.ingestion_id == ingestion_id,
                text(match_cond),
            )
            .order_by(text("lex_score DESC"), CodeChunk.id)
            .limit(top_k)
            .params(q=query, **term_params)
        )
        stmt = _apply_filters(stmt, file_extensions, file_paths)

        rows = (await db.execute(stmt)).all()
        return [
            {
                "chunk": row[0],
                "lex_score": max(0.0, min(1.0, float(row[1] or 0.0))),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # SQLite fallback (unit tests): same terms, weights and coverage, with
    # a simple word/substring matcher standing in for tsvector matching.
    # ------------------------------------------------------------------

    async def _search_fallback(
        self,
        db: AsyncSession,
        query: str,
        terms: list[str],
        repository_id: int,
        ingestion_id: int,
        top_k: int,
        file_extensions: list[str] | None,
        file_paths: list[str] | None,
    ) -> list[dict[str, Any]]:
        base = select(CodeChunk).where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.ingestion_id == ingestion_id,
        )
        all_chunks = (await db.execute(base)).scalars().all()
        filtered_ids = {
            c.id
            for c in (
                await db.execute(_apply_filters(base, file_extensions, file_paths))
            )
            .scalars()
            .all()
        }

        haystacks = {c.id: _fallback_haystack(c) for c in all_chunks}
        n = len(all_chunks)
        usable: list[str] = []
        weights: list[float] = []
        absent_weight = 0.0
        for term in terms:
            df = sum(1 for h in haystacks.values() if _fallback_matches(term, h))
            if df > 0:
                usable.append(term)
                weights.append(idf_weight(df, n))
            else:
                absent_weight += idf_weight(0, n)

        query_lower = query.strip().lower()
        scored: list[tuple[float, int, CodeChunk]] = []
        for chunk in all_chunks:
            if chunk.id not in filtered_ids:
                continue
            if chunk.name and chunk.name.lower() == query_lower:
                scored.append((1.0, chunk.id, chunk))
                continue
            matched = [_fallback_matches(t, haystacks[chunk.id]) for t in usable]
            if any(matched):
                score = weighted_coverage([*matched, False], [*weights, absent_weight])
                scored.append((score, chunk.id, chunk))

        scored.sort(key=lambda t: (-t[0], t[1]))
        return [{"chunk": c, "lex_score": s} for s, _, c in scored[:top_k]]


_FALLBACK_WORD_RE = re.compile(r"[a-z0-9]+")


def _fold(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _fallback_haystack(chunk: CodeChunk) -> tuple[str, set[str]]:
    blob = f"{chunk.name or ''} {chunk.file_path} {chunk.chunk_text}".lower()
    return blob, {_fold(w) for w in _FALLBACK_WORD_RE.findall(blob)}


def _fallback_matches(term: str, haystack: tuple[str, set[str]]) -> bool:
    blob, words = haystack
    term = term.lower()
    if _FALLBACK_WORD_RE.fullmatch(term):
        return _fold(term) in words
    # Identifier / path / multi-part token: match it verbatim.
    return term in blob
