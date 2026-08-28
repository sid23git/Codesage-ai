"""File filtering and ignore policy enforcement for repository ingestion."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

# Directories unconditionally excluded from source scanning
IGNORED_DIRECTORIES: frozenset[str] = frozenset(
    {
        # Version control
        ".git",
        ".svn",
        ".hg",
        ".cvs",
        # Package managers & dependencies
        "node_modules",
        "bower_components",
        "jspm_packages",
        # Python environments & caches
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        ".env_site",
        # Build outputs & artifacts
        "dist",
        "build",
        "out",
        "target",
        "bin",
        "obj",
        "pkg",
        # Coverage reports
        "coverage",
        ".coverage",
        "htmlcov",
        ".nyc_output",
        # IDEs and editors
        ".idea",
        ".vscode",
        ".eclipse",
        ".settings",
        # Framework caches
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        ".parcel-cache",
    }
)

# Extensions for binary, compiled, archive, or media files
IGNORED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Compiled & executable binaries
        ".pyc",
        ".pyo",
        ".pyd",
        ".class",
        ".jar",
        ".war",
        ".ear",
        ".o",
        ".obj",
        ".a",
        ".lib",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".hex",
        ".whl",
        # Archives & compression
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".iso",
        ".dmg",
        # Media: Images, video, audio
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".bmp",
        ".tiff",
        ".webp",
        ".psd",
        ".ai",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".wmv",
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".aac",
        ".pdf",
        # Fonts
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".eot",
        # Databases & binary data stores
        ".db",
        ".sqlite",
        ".sqlite3",
        ".mdb",
        ".parquet",
        ".arrow",
        ".wasm",
    }
)

# Secret and credential file patterns (filenames or wildcard patterns)
SECRET_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pkcs12",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "id_dsa",
    "id_ecdsa",
    "credentials.json",
    "service-account*.json",
    "service_account*.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
)


def is_secret_file(filename: str, relative_path: str = "") -> bool:
    """Check if a file matches known secret/credential naming patterns.

    Parameters
    ----------
    filename:
        Basename of the file (e.g. ``".env.local"`` or ``"id_rsa"``).
    relative_path:
        Relative path for pattern matching.

    Returns
    -------
    bool
        True if the file appears to be a secret/credential file.
    """
    fname_lower = filename.lower()
    rel_lower = relative_path.replace("\\", "/").lower()

    for pattern in SECRET_PATTERNS:
        if fnmatch.fnmatch(fname_lower, pattern):
            return True
        if fnmatch.fnmatch(rel_lower, pattern) or fnmatch.fnmatch(
            os.path.basename(rel_lower), pattern
        ):
            return True

    return False


def is_binary_content(file_path: Path, sample_size: int = 8192) -> bool:
    """Detect if a file contains binary content by inspecting leading bytes.

    Parameters
    ----------
    file_path:
        Path to the file on disk.
    sample_size:
        Number of bytes to sample from the start of the file.

    Returns
    -------
    bool
        True if the file contains null bytes (binary indicator).
    """
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
            if not chunk:
                return False
            # Standard null-byte check for binary detection
            if b"\x00" in chunk:
                return True
            # Attempt UTF-8 decoding of sample
            try:
                chunk.decode("utf-8")
                return False
            except UnicodeDecodeError:
                # If cannot decode as UTF-8, check if non-ASCII control chars dominate
                control_chars = bytearray(
                    {7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100))
                )
                non_text = chunk.translate(None, control_chars)
                return len(non_text) / len(chunk) > 0.30
    except (OSError, PermissionError):
        return True


class FileFilterPolicy:
    """Configurable filter policy for accepting or rejecting repository files."""

    def __init__(
        self,
        max_single_file_size: int = 2_097_152,  # 2 MB
        ignored_directories: frozenset[str] | None = None,
        ignored_extensions: frozenset[str] | None = None,
    ) -> None:
        self.max_single_file_size = max_single_file_size
        self.ignored_directories = ignored_directories or IGNORED_DIRECTORIES
        self.ignored_extensions = ignored_extensions or IGNORED_EXTENSIONS

    def should_ignore_directory(self, dir_name: str) -> bool:
        """Check whether a directory should be skipped entirely during scanning."""
        return (
            dir_name in self.ignored_directories
            or dir_name.lower() in self.ignored_directories
        )

    def evaluate_file(
        self, file_path: Path, relative_path: str
    ) -> tuple[bool, str | None]:
        """Evaluate if a file should be accepted or ignored.

        Parameters
        ----------
        file_path:
            Absolute or resolved path to the file.
        relative_path:
            Relative path within the repository root.

        Returns
        -------
        tuple[bool, str | None]
            (True, reason) if ignored, (False, None) if accepted.
        """
        filename = file_path.name
        ext = file_path.suffix.lower()

        # 1. Secret / credential files check
        if is_secret_file(filename, relative_path):
            return True, "secret_or_credential_file"

        # 2. Known binary extension check
        if ext in self.ignored_extensions:
            return True, "binary_extension"

        # 3. File size check
        try:
            stat = file_path.stat()
            if stat.st_size > self.max_single_file_size:
                return True, f"file_size_exceeded_{stat.st_size}_bytes"
        except (OSError, PermissionError):
            return True, "stat_error"

        # 4. Content-based binary check
        if is_binary_content(file_path):
            return True, "binary_content"

        return False, None
