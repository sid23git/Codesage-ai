"""Hybrid retrieval engine using deterministic Linear Score Fusion.

Combines dense semantic retrieval (pgvector cosine distance) and
lexical retrieval (PostgreSQL FTS / symbol matching) into a single
ranked result list.

Scoring formula
---------------
    S_final(c) = min(1.0,
        w_sem  * S_sem(c)
      + w_lex  * S_lex(c)
      + bonus_symbol(c)
      + bonus_path(c)
    )

Where:
    w_sem         = 0.70  (semantic weight)
    w_lex         = 0.30  (lexical weight)
    S_sem(c)      = max(0, 1 - cosine_distance)  in [0, 1]
    S_lex(c)      = min(1, ts_rank_cd / 0.5)     in [0, 1]
    bonus_symbol  = 0.20  if query matches chunk.name exactly (case-insensitive)
    bonus_path    = 0.10  if query token appears in chunk.file_path (case-insensitive)

Note: call-graph / import-graph ranking is explicitly deferred to Milestone 6.
"""

from __future__ import annotations

from typing import Any

from app.models.code_chunk import CodeChunk
from app.schemas.rag import ChunkSearchResult

# ── Score weights ────────────────────────────────────────────────────────────
_W_SEM: float = 0.70
_W_LEX: float = 0.30
_BONUS_SYMBOL: float = 0.20
_BONUS_PATH: float = 0.10


def _compute_score(
    sem_score: float,
    lex_score: float,
    query_lower: str,
    chunk: CodeChunk,
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

    bonus = 0.0

    # Exact symbol name match bonus
    if chunk.name and chunk.name.lower() == query_lower:
        bonus += _BONUS_SYMBOL
        if "keyword" not in sources:
            sources.append("keyword")

    # Path token match bonus — check if any word in the query appears in the path
    if any(token and token in chunk.file_path.lower() for token in query_lower.split()):
        bonus += _BONUS_PATH

    score = min(1.0, _W_SEM * sem_score + _W_LEX * lex_score + bonus)
    return score, sources


def fuse(
    sem_results: list[dict[str, Any]],
    lex_results: list[dict[str, Any]],
    query: str,
    top_k: int,
    min_score: float | None = None,
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
        Original search query (used for symbol/path bonuses).
    top_k:
        Maximum results to return.
    min_score:
        Optional minimum score threshold — chunks below this are dropped.

    Returns
    -------
    list[ChunkSearchResult]
        Final ranked and serialised results.
    """
    query_lower = query.lower().strip()

    # Merge all candidates into a per-chunk-id score table
    scores: dict[int, dict[str, Any]] = {}

    for entry in sem_results:
        chunk: CodeChunk = entry["chunk"]
        cid = chunk.id
        if cid not in scores:
            scores[cid] = {"chunk": chunk, "sem_score": 0.0, "lex_score": 0.0}
        scores[cid]["sem_score"] = max(scores[cid]["sem_score"], entry["sem_score"])

    for entry in lex_results:
        chunk = entry["chunk"]
        cid = chunk.id
        if cid not in scores:
            scores[cid] = {"chunk": chunk, "sem_score": 0.0, "lex_score": 0.0}
        scores[cid]["lex_score"] = max(scores[cid]["lex_score"], entry["lex_score"])

    # Compute final scores
    ranked: list[tuple[float, list[str], CodeChunk]] = []
    for entry in scores.values():
        chunk = entry["chunk"]
        score, sources = _compute_score(
            sem_score=entry["sem_score"],
            lex_score=entry["lex_score"],
            query_lower=query_lower,
            chunk=chunk,
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
