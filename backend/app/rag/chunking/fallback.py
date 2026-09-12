"""Sliding-window line-based fallback chunker.

Applied to files whose language is unknown or unsupported by the
structured chunkers, or when structured parsing fails.
"""

from __future__ import annotations

from app.rag.chunking._models import RawChunk

_DEFAULT_CHUNK_LINES = 50
_DEFAULT_OVERLAP_LINES = 10


class FallbackChunker:
    """Chunks any text file by fixed-size line windows with overlap."""

    def __init__(
        self,
        chunk_lines: int = _DEFAULT_CHUNK_LINES,
        overlap_lines: int = _DEFAULT_OVERLAP_LINES,
    ) -> None:
        if overlap_lines >= chunk_lines:
            raise ValueError("overlap_lines must be less than chunk_lines")
        self._chunk_lines = chunk_lines
        self._overlap_lines = overlap_lines

    def chunk(self, file_path: str, language: str | None, text: str) -> list[RawChunk]:
        """Split *text* into overlapping line-window chunks.

        Parameters
        ----------
        file_path:
            Repository-relative path (for metadata only).
        language:
            Canonical language label or ``None``.
        text:
            Full source text.
        """
        lines = text.split("\n")
        chunks: list[RawChunk] = []
        step = self._chunk_lines - self._overlap_lines
        start = 0

        while start < len(lines):
            end = min(start + self._chunk_lines, len(lines))
            chunk_text = "\n".join(lines[start:end])

            if chunk_text.strip():
                chunks.append(
                    RawChunk(
                        file_path=file_path,
                        start_line=start + 1,  # 1-indexed
                        end_line=end,
                        language=language,
                        chunk_type="block",
                        name=None,
                        chunk_text=chunk_text,
                    )
                )

            if end == len(lines):
                break

            start += step

        return chunks
