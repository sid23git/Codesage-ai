"""Python AST-based chunker.

Extracts top-level functions and classes as individual chunks with exact
line-number attribution from the Python ``ast`` standard library.
Falls back to sliding-window chunking when the file cannot be parsed.
"""

from __future__ import annotations

import ast
import logging

from app.rag.chunking._models import RawChunk
from app.rag.chunking.fallback import FallbackChunker

logger = logging.getLogger(__name__)


class PythonAstChunker:
    """Chunks Python source files by AST boundaries."""

    def chunk(self, file_path: str, language: str | None, text: str) -> list[RawChunk]:
        """Parse *text* and emit one chunk per top-level function/class.

        Parameters
        ----------
        file_path:
            Repository-relative path (for metadata only).
        language:
            Canonical language label, expected ``"Python"``.
        text:
            Full source text of the file.
        """
        lines = text.split("\n")
        chunks: list[RawChunk] = []

        try:
            tree = ast.parse(text, filename=file_path)
        except SyntaxError:
            logger.debug("SyntaxError in %s — using fallback chunker", file_path)
            return FallbackChunker().chunk(file_path, language, text)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = node.end_lineno or node.lineno
                chunks.append(
                    RawChunk(
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=end,
                        language=language,
                        chunk_type="function",
                        name=node.name,
                        chunk_text="\n".join(lines[node.lineno - 1 : end]),
                    )
                )
            elif isinstance(node, ast.ClassDef):
                end = node.end_lineno or node.lineno
                chunks.append(
                    RawChunk(
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=end,
                        language=language,
                        chunk_type="class",
                        name=node.name,
                        chunk_text="\n".join(lines[node.lineno - 1 : end]),
                    )
                )
            # Other top-level statements (imports, assignments) are intentionally
            # omitted from individual chunks in the MVP; they appear in the
            # fallback path when no functions/classes are found.

        if not chunks:
            return FallbackChunker().chunk(file_path, language, text)

        return chunks
