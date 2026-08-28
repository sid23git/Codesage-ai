"""Unit tests for archive extraction, path traversal defense, and bomb protection."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from app.ingestion.archive import safe_extract_tarball
from app.ingestion.exceptions import (
    ArchiveExtractionError,
    SecurityViolationError,
)


def _create_tarball(files: dict[str, bytes]) -> bytes:
    """Create a gzipped tarball in memory from a path -> content dict."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestArchiveExtractionSuccess:
    """Verify standard valid archive extraction."""

    def test_extract_valid_github_tarball(self, tmp_path: Path) -> None:
        files = {
            "octocat-hello-world-a1b2c3d/main.py": b"print('hello world')\n",
            "octocat-hello-world-a1b2c3d/README.md": b"# Hello World\n",
            "octocat-hello-world-a1b2c3d/src/utils.py": (
                b"def add(a, b): return a + b\n"
            ),
        }
        archive = _create_tarball(files)
        dest = tmp_path / "extracted"

        root_dir, commit_sha = safe_extract_tarball(archive, dest)

        assert root_dir.exists()
        assert (root_dir / "main.py").exists()
        assert (root_dir / "README.md").exists()
        assert (root_dir / "src" / "utils.py").exists()
        assert (root_dir / "main.py").read_text(
            encoding="utf-8"
        ) == "print('hello world')\n"
        assert commit_sha == "a1b2c3d"

    def test_extract_flat_tarball_without_single_root(self, tmp_path: Path) -> None:
        files = {
            "file1.py": b"x = 1\n",
            "file2.py": b"y = 2\n",
        }
        archive = _create_tarball(files)
        dest = tmp_path / "extracted"

        root_dir, commit_sha = safe_extract_tarball(archive, dest)
        assert (root_dir / "file1.py").exists()
        assert commit_sha is None


class TestArchiveSecurityDefenses:
    """Verify security protections against path traversal, bombs, and bad entries."""

    def test_empty_archive_rejected(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest"
        with pytest.raises(ArchiveExtractionError, match="empty archive"):
            safe_extract_tarball(b"", dest)

    def test_corrupt_archive_rejected(self, tmp_path: Path) -> None:
        dest = tmp_path / "dest"
        with pytest.raises(ArchiveExtractionError, match="Corrupt or unreadable"):
            safe_extract_tarball(b"not-a-tarball-stream-bytes", dest)

    def test_path_traversal_parent_dir_rejected(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="../evil.txt")
            data = b"malicious"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        archive = buf.getvalue()

        dest = tmp_path / "dest"
        with pytest.raises(SecurityViolationError, match="Path traversal detected"):
            safe_extract_tarball(archive, dest)

    def test_path_traversal_absolute_path_rejected(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="/etc/passwd")
            data = b"root:x:0:0"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        archive = buf.getvalue()

        dest = tmp_path / "dest"
        with pytest.raises(SecurityViolationError, match="Path traversal detected"):
            safe_extract_tarball(archive, dest)

    def test_decompression_bomb_size_limit_exceeded(self, tmp_path: Path) -> None:
        files = {
            "bigfile.txt": b"A" * 500,
        }
        archive = _create_tarball(files)
        dest = tmp_path / "dest"

        # Max allowed 200 bytes, archive has 500 bytes uncompressed
        with pytest.raises(
            ArchiveExtractionError, match="maximum uncompressed size limit"
        ):
            safe_extract_tarball(archive, dest, max_uncompressed_bytes=200)

    def test_decompression_bomb_file_count_limit_exceeded(self, tmp_path: Path) -> None:
        files = {f"file_{i}.txt": b"content" for i in range(10)}
        archive = _create_tarball(files)
        dest = tmp_path / "dest"

        # Max allowed 5 files, archive has 10
        with pytest.raises(ArchiveExtractionError, match="maximum file count limit"):
            safe_extract_tarball(archive, dest, max_files=5)
