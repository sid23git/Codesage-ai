"""Safe archive extraction with path traversal and decompression bomb defenses."""

from __future__ import annotations

import io
import logging
import tarfile
from pathlib import Path

from app.ingestion.exceptions import (
    ArchiveExtractionError,
    SecurityViolationError,
)

logger = logging.getLogger(__name__)


def _is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """Ensure the target path resolves strictly inside the base directory."""
    try:
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        return (
            resolved_target == resolved_base or resolved_base in resolved_target.parents
        )
    except (ValueError, RuntimeError):
        return False


def _extract_commit_sha_from_dirname(dirname: str) -> str | None:
    """Extract git commit SHA from GitHub's default archive top-level folder name.

    GitHub archive root directory naming convention: ``{owner}-{repo}-{commit_sha[:7]}``
    """
    parts = dirname.rstrip("/\\").split("-")
    if len(parts) >= 2:
        candidate = parts[-1]
        # Check if candidate looks like a hex commit hash prefix (7-40 chars)
        if 7 <= len(candidate) <= 40 and all(
            c in "0123456789abcdefABCDEF" for c in candidate
        ):
            return candidate.lower()
    return None


def safe_extract_tarball(
    archive_bytes: bytes,
    destination_dir: Path,
    max_uncompressed_bytes: int = 104_857_600,  # 100 MB
    max_files: int = 2000,
) -> tuple[Path, str | None]:
    """Safely extract a tar.gz repository archive with security limit enforcement.

    Guards against:
    - Path traversal attacks (``../``, absolute paths, null bytes)
    - Symlink escapes and unsafe link targets
    - Decompression bombs (excessive uncompressed size or file count)
    - Device and FIFO special files

    Parameters
    ----------
    archive_bytes:
        Raw compressed tarball bytes.
    destination_dir:
        Directory where files should be extracted.
    max_uncompressed_bytes:
        Maximum total uncompressed bytes permitted.
    max_files:
        Maximum number of files allowed in the archive.

    Returns
    -------
    tuple[Path, str | None]
        - Path to the extracted repository source root.
        - Extracted commit SHA if detected from GitHub's root directory name.

    Raises
    ------
    SecurityViolationError
        If an entry attempts path traversal or symlink escape.
    ArchiveExtractionError
        If archive is corrupted, contains invalid entries, or exceeds limits.
    """
    if not archive_bytes:
        raise ArchiveExtractionError("Received empty archive payload.")

    destination_dir = destination_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    try:
        tar_stream = io.BytesIO(archive_bytes)
        with tarfile.open(fileobj=tar_stream, mode="r:*") as tar:
            members = tar.getmembers()

            total_bytes = 0
            file_count = 0
            top_level_entries: set[str] = set()

            # First pass: validate all entries before writing any files to disk
            for member in members:
                # 1. Reject dangerous file types (device nodes, FIFOs)
                if (
                    member.isdev()
                    or member.ischr()
                    or member.isblk()
                    or member.isfifo()
                ):
                    raise SecurityViolationError(
                        f"Special or device file '{member.name}' is forbidden in "
                        "repository archives."
                    )

                # 2. Path traversal validation
                norm_name = member.name.replace("\\", "/")
                if (
                    norm_name.startswith("/")
                    or ".." in norm_name.split("/")
                    or "\x00" in norm_name
                ):
                    raise SecurityViolationError(
                        f"Path traversal detected in archive entry: '{member.name}'."
                    )

                entry_target = (destination_dir / member.name).resolve()
                if not _is_safe_path(destination_dir, entry_target):
                    raise SecurityViolationError(
                        f"Archive entry '{member.name}' resolves outside "
                        "destination directory."
                    )

                # 3. Symlink / Hardlink escape defense
                if member.issym() or member.islnk():
                    link_target_name = member.linkname.replace("\\", "/")
                    if (
                        link_target_name.startswith("/")
                        or ".." in link_target_name.split("/")
                        or "\x00" in link_target_name
                    ):
                        raise SecurityViolationError(
                            f"Unsafe link target '{member.linkname}' detected in "
                            f"entry '{member.name}'."
                        )

                # 4. Decompression bomb limits
                total_bytes += member.size
                if total_bytes > max_uncompressed_bytes:
                    raise ArchiveExtractionError(
                        "Archive exceeds maximum uncompressed size limit of "
                        f"{max_uncompressed_bytes} bytes."
                    )

                if member.isfile():
                    file_count += 1
                    if file_count > max_files:
                        raise ArchiveExtractionError(
                            "Archive exceeds maximum file count limit of "
                            f"{max_files} files."
                        )

                # Track top-level directories
                first_segment = norm_name.split("/")[0]
                if first_segment:
                    top_level_entries.add(first_segment)

            # Second pass: safe extraction
            for member in members:
                entry_target = destination_dir / member.name
                if member.isdir():
                    entry_target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    entry_target.parent.mkdir(parents=True, exist_ok=True)
                    f_obj = tar.extractfile(member)
                    if f_obj is not None:
                        with open(entry_target, "wb") as out_f:
                            # Stream in 64 KB chunks
                            while chunk := f_obj.read(65536):
                                out_f.write(chunk)
                # Symlinks and hardlinks are safely skipped during ingestion extraction

    except (tarfile.TarError, EOFError, OSError) as exc:
        if isinstance(exc, (SecurityViolationError, ArchiveExtractionError)):
            raise
        logger.warning("Failed to decompress tar archive: %s", exc)
        raise ArchiveExtractionError(f"Corrupt or unreadable archive: {exc}") from exc

    # Identify source root folder (<owner>-<repo>-<sha>/)
    extracted_root = destination_dir
    commit_sha: str | None = None

    if len(top_level_entries) == 1:
        single_root_name = next(iter(top_level_entries))
        candidate_root = destination_dir / single_root_name
        if candidate_root.is_dir():
            extracted_root = candidate_root
            commit_sha = _extract_commit_sha_from_dirname(single_root_name)

    return extracted_root, commit_sha
