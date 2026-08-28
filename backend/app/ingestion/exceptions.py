"""Typed exception hierarchy for repository ingestion pipeline."""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for all repository ingestion errors."""


class IngestionLimitExceededError(IngestionError):
    """Raised when repository exceeds file count or size resource limits."""


class SecurityViolationError(IngestionError):
    """Raised when an illegal file operation or traversal attempt is detected."""


class ArchiveExtractionError(IngestionError):
    """Raised when archive decompression fails, is corrupt, or triggers limits."""


class UnsupportedSourceError(IngestionError):
    """Raised when a repository source URL or location is unsupported."""
