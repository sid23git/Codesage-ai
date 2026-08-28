"""Repository ingestion engine."""

from app.ingestion.archive import safe_extract_tarball
from app.ingestion.exceptions import (
    ArchiveExtractionError,
    IngestionError,
    IngestionLimitExceededError,
    SecurityViolationError,
    UnsupportedSourceError,
)
from app.ingestion.filter import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    FileFilterPolicy,
    is_binary_content,
    is_secret_file,
)
from app.ingestion.languages import EXTENSION_LANGUAGE_MAP, detect_language
from app.ingestion.scanner import RepositoryScanner, ScannedFile, ScanResult

__all__ = [
    "EXTENSION_LANGUAGE_MAP",
    "IGNORED_DIRECTORIES",
    "IGNORED_EXTENSIONS",
    "ArchiveExtractionError",
    "FileFilterPolicy",
    "IngestionError",
    "IngestionLimitExceededError",
    "RepositoryScanner",
    "ScanResult",
    "ScannedFile",
    "SecurityViolationError",
    "UnsupportedSourceError",
    "detect_language",
    "is_binary_content",
    "is_secret_file",
    "safe_extract_tarball",
]
