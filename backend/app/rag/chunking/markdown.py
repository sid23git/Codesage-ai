"""Markdown section chunker.

Splits Markdown documents at header boundaries (``#``, ``##``, ``###``, etc.)
and treats each section as an individual chunk.
Falls back to the sliding-window chunker for documents with no headers.
"""

from __future__ import annotations

import re

from app.rag.chunking._models import RawChunk
from app.rag.chunking.fallback import FallbackChunker

_HEADER_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


class MarkdownChunker:
    """Chunks Markdown files at heading boundaries."""

    def chunk(self, file_path: str, language: str | None, text: str) -> list[RawChunk]:
        """Split *text* at Markdown section headers.

        Parameters
        ----------
        file_path:
            Repository-relative path (for metadata only).
        language:
            Canonical language label, expected ``"Markdown"``.
        text:
            Full source text of the file.
        """
        matches = list(_HEADER_RE.finditer(text))

        if not matches:
            return FallbackChunker().chunk(file_path, language, text)

        chunks: list[RawChunk] = []

        for i, match in enumerate(matches):
            name = match.group(2).strip()
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)

            chunk_text = text[start_pos:end_pos].rstrip()
            if not chunk_text.strip():
                continue

            start_line = text.count("\n", 0, start_pos) + 1
            end_line = start_line + chunk_text.count("\n")

            chunks.append(
                RawChunk(
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    chunk_type="doc_section",
                    name=name,
                    chunk_text=chunk_text,
                )
            )

        return chunks if chunks else FallbackChunker().chunk(file_path, language, text)
