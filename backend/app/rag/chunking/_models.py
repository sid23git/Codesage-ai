"""Shared data models for the chunking subsystem.

Isolated here to prevent circular imports between chunker modules.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class RawChunk:
    """A parsed code chunk before embedding."""

    file_path: str
    start_line: int
    end_line: int
    language: str | None
    chunk_type: str
    name: str | None
    chunk_text: str

    @property
    def content_hash(self) -> str:
        """Deterministically hash the trimmed chunk content (SHA-256 hex)."""
        return hashlib.sha256(self.chunk_text.strip().encode("utf-8")).hexdigest()
