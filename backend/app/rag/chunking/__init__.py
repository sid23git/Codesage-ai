"""Code-aware chunking engine for RAG pipelines.

Usage
-----
    from app.rag.chunking import chunk_file, RawChunk

    chunks: list[RawChunk] = chunk_file(
        file_path="app/core/security.py",
        language="Python",
        text=source_text,
    )
"""

from __future__ import annotations

from app.rag.chunking._models import RawChunk
from app.rag.chunking.ast_python import PythonAstChunker
from app.rag.chunking.fallback import FallbackChunker
from app.rag.chunking.markdown import MarkdownChunker
from app.rag.chunking.structural import StructuralBlockChunker

_STRUCTURAL_LANGUAGES = frozenset(
    {"JavaScript", "TypeScript", "Go", "Rust", "Java", "C", "C++", "C#"}
)


def chunk_file(file_path: str, language: str | None, text: str) -> list[RawChunk]:
    """Route a source file to the most appropriate chunker.

    Parameters
    ----------
    file_path:
        Relative path of the file within the repository root.
    language:
        Canonical language name detected by M4 (e.g. ``"Python"``),
        or ``None`` for unknown files.
    text:
        Full UTF-8 source text of the file.

    Returns
    -------
    list[RawChunk]
        One or more non-overlapping chunks with source-location metadata.
        Always returns at least one chunk for non-empty files.
    """
    if not text.strip():
        return []

    if language == "Python":
        return PythonAstChunker().chunk(file_path, language, text)
    if language == "Markdown":
        return MarkdownChunker().chunk(file_path, language, text)
    if language in _STRUCTURAL_LANGUAGES:
        return StructuralBlockChunker().chunk(file_path, language, text)
    return FallbackChunker().chunk(file_path, language, text)


__all__ = [
    "FallbackChunker",
    "MarkdownChunker",
    "PythonAstChunker",
    "RawChunk",
    "StructuralBlockChunker",
    "chunk_file",
]
