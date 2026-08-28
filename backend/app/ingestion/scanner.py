"""Repository scanner, file discovery, metadata extraction, and structure analysis."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ingestion.exceptions import IngestionLimitExceededError
from app.ingestion.filter import FileFilterPolicy
from app.ingestion.languages import detect_language

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannedFile:
    """Metadata extracted for an accepted repository source file."""

    path: str
    name: str
    extension: str
    language: str | None
    size_bytes: int
    line_count: int | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary representation."""
        return {
            "path": self.path,
            "name": self.name,
            "extension": self.extension,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "line_count": self.line_count,
        }


@dataclass
class ScanResult:
    """Aggregated results of scanning a repository source tree."""

    file_count: int = 0
    total_size_bytes: int = 0
    total_lines: int = 0
    primary_language: str | None = None
    language_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    directory_summary: dict[str, int] = field(default_factory=dict)
    file_catalog: list[dict[str, Any]] = field(default_factory=list)


def count_lines(file_path: Path) -> int | None:
    """Safely count lines in a text file.

    Parameters
    ----------
    file_path:
        Path to the file on disk.

    Returns
    -------
    int | None
        Number of lines in the file, or None if unreadable.
    """
    try:
        # Try UTF-8 first (most common for source code), then latin-1
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)
        except UnicodeError:
            with open(file_path, encoding="latin-1", errors="replace") as f:
                return sum(1 for _ in f)
    except (OSError, PermissionError) as exc:
        logger.debug("Failed to count lines in %s: %s", file_path, exc)
        return None


class RepositoryScanner:
    """Discovers source files, extracts metadata, and compiles structural statistics."""

    def __init__(
        self,
        filter_policy: FileFilterPolicy | None = None,
        max_file_count: int = 2000,
        max_repo_size_bytes: int = 104_857_600,  # 100 MB
    ) -> None:
        self.filter_policy = filter_policy or FileFilterPolicy()
        self.max_file_count = max_file_count
        self.max_repo_size_bytes = max_repo_size_bytes

    def scan_repository(self, root_dir: Path) -> ScanResult:
        """Recursively walk the repository directory and discover source files.

        Parameters
        ----------
        root_dir:
            Root path of the extracted repository source.

        Returns
        -------
        ScanResult
            Complete structural analysis and file catalog.

        Raises
        ------
        IngestionLimitExceededError
            If total file count or total uncompressed size exceeds limits.
        """
        root_dir = root_dir.resolve()
        result = ScanResult()
        scanned_files: list[ScannedFile] = []

        language_bytes: dict[str, int] = {}
        language_files: dict[str, int] = {}
        language_lines: dict[str, int] = {}
        directory_counts: dict[str, int] = {}

        for current_root, dir_names, file_names in os.walk(root_dir):
            current_root_path = Path(current_root)

            # In-place prune ignored directories to prevent walking into them
            dir_names[:] = [
                d
                for d in dir_names
                if not self.filter_policy.should_ignore_directory(d)
            ]

            for filename in file_names:
                file_path = current_root_path / filename

                # Compute relative path with standard forward slashes
                try:
                    rel_path = file_path.relative_to(root_dir).as_posix()
                except ValueError:
                    continue

                # Filter policy check
                should_ignore, _reason = self.filter_policy.evaluate_file(
                    file_path, rel_path
                )
                if should_ignore:
                    continue

                # Collect file metrics
                try:
                    file_size = file_path.stat().st_size
                except (OSError, PermissionError):
                    continue

                # Detect language
                detected_lang = detect_language(file_path)
                lines = count_lines(file_path)

                scanned = ScannedFile(
                    path=rel_path,
                    name=filename,
                    extension=file_path.suffix.lower(),
                    language=detected_lang,
                    size_bytes=file_size,
                    line_count=lines,
                )
                scanned_files.append(scanned)

                # Update running totals
                result.file_count += 1
                result.total_size_bytes += file_size
                if lines is not None:
                    result.total_lines += lines

                # Enforce repository limits
                if result.file_count > self.max_file_count:
                    raise IngestionLimitExceededError(
                        "Repository file count exceeds maximum limit of "
                        f"{self.max_file_count} files."
                    )
                if result.total_size_bytes > self.max_repo_size_bytes:
                    raise IngestionLimitExceededError(
                        "Repository source size exceeds maximum limit of "
                        f"{self.max_repo_size_bytes} bytes."
                    )

                # Directory structure aggregation
                parts = rel_path.split("/")
                top_dir = parts[0] if len(parts) > 1 else "<root>"
                directory_counts[top_dir] = directory_counts.get(top_dir, 0) + 1

                # Language statistics aggregation
                if detected_lang:
                    language_files[detected_lang] = (
                        language_files.get(detected_lang, 0) + 1
                    )
                    language_bytes[detected_lang] = (
                        language_bytes.get(detected_lang, 0) + file_size
                    )
                    language_lines[detected_lang] = language_lines.get(
                        detected_lang, 0
                    ) + (lines or 0)

        # Sort file catalog by relative path
        scanned_files.sort(key=lambda f: f.path)
        result.file_catalog = [f.to_dict() for f in scanned_files]
        result.directory_summary = directory_counts

        # Build language stats mapping
        all_languages = sorted(language_files.keys())
        for lang in all_languages:
            result.language_stats[lang] = {
                "files": language_files[lang],
                "bytes": language_bytes[lang],
                "lines": language_lines[lang],
            }

        # Determine primary language (language with highest total bytes)
        if language_bytes:
            result.primary_language = max(language_bytes, key=language_bytes.get)  # type: ignore[arg-type]

        return result
