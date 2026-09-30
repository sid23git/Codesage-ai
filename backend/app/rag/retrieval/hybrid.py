"""Hybrid retrieval engine using deterministic Linear Score Fusion.

Combines dense semantic retrieval (pgvector cosine distance), lexical
retrieval (PostgreSQL FTS / symbol matching) and structural metadata
signals (file path, symbol name, repository-overview role) into a single
ranked result list.

Scoring formula
---------------
    S_final(c) = min(1.0,
        w_sem  * S_sem(c)
      + w_lex  * S_lex(c)
      + bonus_symbol(c)
      + bonus_path(c)
      + bonus_overview(c)
    )

Where:
    w_sem          = 0.70  (semantic weight)
    w_lex          = 0.30  (lexical weight)
    S_sem(c)       = max(0, 1 - cosine_distance)            in [0, 1]
    S_lex(c)       = IDF-weighted query-term coverage       in [0, 1]
                     (see ``keyword.py``)
    bonus_symbol   = 0.20  if the query equals chunk.name (case-insensitive)
    bonus_path     = 0.10  if a content word of the query equals a whole
                           component of chunk.file_path (stopwords, file
                           extensions and sub-word fragments never count)
                           AND the chunk already has content evidence of
                           its own: w_sem*S_sem + w_lex*S_lex >= 0.05.
                           The path bonus amplifies evidence; it never
                           creates it.
    bonus_overview = 0.15  if the query is a broad repository-level question
                           (``is_broad_repository_question``) AND the chunk
                           is a structural overview chunk -- root README
                           introduction/overview sections, architecture
                           docs, or the entry point (``is_overview_chunk``).

Non-evidence chunks -- comment-only source chunks (``# Keep directory``, a
one-line ``__init__.py`` comment) and ignore-pattern files (``.gitignore``)
-- are dropped unless the query names that file or is an exact symbol
match: they contain nothing citable, only shared vocabulary.

Note: call-graph / import-graph ranking is explicitly deferred to Milestone 6.
"""

from __future__ import annotations

from typing import Any

from app.models.code_chunk import CodeChunk
from app.rag.retrieval.query_analysis import (
    is_broad_repository_question,
    is_non_evidence_chunk,
    is_overview_chunk,
    path_matches_query,
)
from app.schemas.rag import ChunkSearchResult

# ── Score weights ────────────────────────────────────────────────────────────
_W_SEM: float = 0.70
_W_LEX: float = 0.30
_BONUS_SYMBOL: float = 0.20
_BONUS_PATH: float = 0.10
_BONUS_OVERVIEW: float = 0.15
# Minimum content evidence (w_sem*S_sem + w_lex*S_lex) a chunk needs before a
# path match may add its bonus -- a bare filename coincidence is not evidence.
_PATH_BONUS_MIN_CONTENT: float = 0.05


def _compute_score(
    sem_score: float,
    lex_score: float,
    query_lower: str,
    chunk: CodeChunk,
    *,
    broad_query: bool = False,
) -> tuple[float, list[str]]:
    """Compute the final Linear Score Fusion score for *chunk*.

    Returns
    -------
    tuple[float, list[str]]
        ``(final_score, retrieval_sources)``
    """
    sources: list[str] = []

    if sem_score > 0.0:
        sources.append("semantic")
    if lex_score > 0.0:
        sources.append("keyword")

    content = _W_SEM * sem_score + _W_LEX * lex_score
    bonus = 0.0

    # Exact symbol name match bonus
    if chunk.name and chunk.name.lower() == query_lower:
        bonus += _BONUS_SYMBOL
        if "keyword" not in sources:
            sources.append("keyword")

    # Whole-word path match bonus -- only on top of existing content evidence
    if content >= _PATH_BONUS_MIN_CONTENT and path_matches_query(
        chunk.file_path, query_lower
    ):
        bonus += _BONUS_PATH

    # Repository-overview bonus for broad questions
    if broad_query and is_overview_chunk(chunk.file_path, chunk.name, chunk.start_line):
        bonus += _BONUS_OVERVIEW
        sources.append("overview")

    score = min(1.0, content + bonus)
    return score, sources


def fuse(
    sem_results: list[dict[str, Any]],
    lex_results: list[dict[str, Any]],
    query: str,
    top_k: int,
    min_score: float | None = None,
    overview_results: list[dict[str, Any]] | None = None,
) -> list[ChunkSearchResult]:
    """Merge, score, deduplicate, and rank candidate chunks.

    Parameters
    ----------
    sem_results:
        Output from ``VectorRetriever.search`` — list of dicts with
        ``{"chunk": CodeChunk, "sem_score": float}``.
    lex_results:
        Output from ``KeywordRetriever.search`` — list of dicts with
        ``{"chunk": CodeChunk, "lex_score": float}``.
    query:
        Original search query (used for symbol/path/overview bonuses).
    top_k:
        Maximum results to return.
    min_score:
        Optional minimum score threshold — chunks below this are dropped.
    overview_results:
        Optional output from ``OverviewRetriever.search`` (same shape as
        *sem_results*) — structural candidates for broad questions.

    Returns
    -------
    list[ChunkSearchResult]
        Final ranked and serialised results.
    """
    query_lower = query.lower().strip()
    broad_query = is_broad_repository_question(query)

    # Merge all candidates into a per-chunk-id score table
    scores: dict[int, dict[str, Any]] = {}

    def _entry(chunk: CodeChunk) -> dict[str, Any]:
        if chunk.id not in scores:
            scores[chunk.id] = {"chunk": chunk, "sem_score": 0.0, "lex_score": 0.0}
        return scores[chunk.id]

    for entry in [*sem_results, *(overview_results or [])]:
        row = _entry(entry["chunk"])
        row["sem_score"] = max(row["sem_score"], entry["sem_score"])

    for entry in lex_results:
        row = _entry(entry["chunk"])
        row["lex_score"] = max(row["lex_score"], entry["lex_score"])

    # Compute final scores
    ranked: list[tuple[float, list[str], CodeChunk]] = []
    for entry in scores.values():
        chunk = entry["chunk"]
        exact_symbol = bool(chunk.name) and chunk.name.lower() == query_lower
        if not exact_symbol and is_non_evidence_chunk(
            chunk.chunk_text, chunk.file_path, query
        ):
            continue
        score, sources = _compute_score(
            sem_score=entry["sem_score"],
            lex_score=entry["lex_score"],
            query_lower=query_lower,
            chunk=chunk,
            broad_query=broad_query,
        )
        if min_score is not None and score < min_score:
            continue
        ranked.append((score, sources, chunk))

    # Sort by score descending, stable
    ranked.sort(key=lambda t: t[0], reverse=True)

    results: list[ChunkSearchResult] = []
    for score, sources, chunk in ranked[:top_k]:
        results.append(
            ChunkSearchResult(
                chunk_id=chunk.id,
                file_path=chunk.file_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                language=chunk.language,
                chunk_type=chunk.chunk_type or "block",
                name=chunk.name,
                chunk_text=chunk.chunk_text,
                score=round(score, 6),
                retrieval_sources=sources,
            )
        )

    return results
