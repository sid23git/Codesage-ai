"""Unit tests for repository scanner and structure metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.exceptions import IngestionLimitExceededError
from app.ingestion.scanner import RepositoryScanner, count_lines


class TestLineCounting:
    """Verify safe line count extraction."""

    def test_count_lines_standard_text(self, tmp_path: Path) -> None:
        p = tmp_path / "code.py"
        p.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        assert count_lines(p) == 3

    def test_count_lines_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.py"
        p.write_text("", encoding="utf-8")
        assert count_lines(p) == 0

    def test_count_lines_single_line_no_newline(self, tmp_path: Path) -> None:
        p = tmp_path / "single.txt"
        p.write_text("hello", encoding="utf-8")
        assert count_lines(p) == 1


class TestRepositoryScanner:
    """Verify repository source tree discovery and metrics computation."""

    def test_scan_repository_structure(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "my_project"
        repo_root.mkdir()

        # Root files
        (repo_root / "README.md").write_text(
            "# Project\nOverview line\n", encoding="utf-8"
        )
        (repo_root / "main.py").write_text(
            "import sys\n\ndef main():\n    pass\n", encoding="utf-8"
        )

        # Nested src dir
        src = repo_root / "src"
        src.mkdir()
        (src / "app.py").write_text("def app():\n    return 42\n", encoding="utf-8")
        (src / "utils.ts").write_text(
            "export const add = (a: number, b: number) => a + b;\n", encoding="utf-8"
        )

        # Ignored dir
        node_modules = repo_root / "node_modules"
        node_modules.mkdir()
        (node_modules / "dummy.js").write_text(
            "console.log('skip');\n", encoding="utf-8"
        )

        # Secret file (should be skipped)
        (repo_root / ".env").write_text("SECRET=123\n", encoding="utf-8")

        scanner = RepositoryScanner()
        result = scanner.scan_repository(repo_root)

        assert result.file_count == 4
        assert result.total_lines > 0
        assert result.total_size_bytes > 0
        assert "Python" in result.language_stats
        assert "TypeScript" in result.language_stats
        assert "Markdown" in result.language_stats
        assert result.language_stats["Python"]["files"] == 2
        assert result.language_stats["TypeScript"]["files"] == 1
        assert result.language_stats["Markdown"]["files"] == 1

        # Check directory summary
        assert "<root>" in result.directory_summary
        assert result.directory_summary["<root>"] == 2
        assert result.directory_summary["src"] == 2

        # Check file catalog
        paths = [f["path"] for f in result.file_catalog]
        assert "README.md" in paths
        assert "main.py" in paths
        assert "src/app.py" in paths
        assert "src/utils.ts" in paths
        assert ".env" not in paths
        assert "node_modules/dummy.js" not in paths

    def test_file_count_limit_exceeded_raises(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        for i in range(10):
            (repo_root / f"file_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")

        scanner = RepositoryScanner(max_file_count=5)
        with pytest.raises(
            IngestionLimitExceededError, match="file count exceeds maximum limit"
        ):
            scanner.scan_repository(repo_root)

    def test_repo_size_limit_exceeded_raises(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "big.py").write_text("A" * 1000, encoding="utf-8")

        scanner = RepositoryScanner(max_repo_size_bytes=500)
        with pytest.raises(
            IngestionLimitExceededError, match="source size exceeds maximum limit"
        ):
            scanner.scan_repository(repo_root)
