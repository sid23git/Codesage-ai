"""Structural block chunker for C-family and block-structured languages.

Uses regex pattern matching to identify named declarations
(functions, classes, structs, interfaces) in languages such as
JavaScript, TypeScript, Go, Rust, Java, C, C++, and C#.

Falls back to the sliding-window chunker when no declarations are found
or the file is too short to benefit from structural splitting.
"""

from __future__ import annotations

import re

from app.rag.chunking._models import RawChunk
from app.rag.chunking.fallback import FallbackChunker

# Matches top-level or class-member function/class/interface/struct declarations
# in a variety of block-structured languages.
_DECLARATION_RE = re.compile(
    r"^(?:export\s+)?(?:public\s+|private\s+|protected\s+)?"
    r"(?:static\s+)?(?:async\s+)?(?:abstract\s+)?"
    r"(?:class|struct|interface|enum|function|func|fn|def|sub|void|int|bool|string|var|const|let)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)[\s\(<\{:]",
    re.MULTILINE,
)


class StructuralBlockChunker:
    """Chunks block-structured source files using declaration boundary heuristics."""

    def chunk(self, file_path: str, language: str | None, text: str) -> list[RawChunk]:
        """Split *text* at named declaration boundaries.

        Parameters
        ----------
        file_path:
            Repository-relative path (for metadata only).
        language:
            Canonical language label.
        text:
            Full source text of the file.
        """
        matches = list(_DECLARATION_RE.finditer(text))

        if not matches:
            return FallbackChunker().chunk(file_path, language, text)

        chunks: list[RawChunk] = []

        for i, match in enumerate(matches):
            name = match.group(1)
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
                    chunk_type="block",
                    name=name,
                    chunk_text=chunk_text,
                )
            )

        return chunks if chunks else FallbackChunker().chunk(file_path, language, text)
