"""Unit tests for file filtering and ignore policies."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.filter import (
    FileFilterPolicy,
    is_binary_content,
    is_secret_file,
)


class TestSecretDetection:
    """Verify detection of secret and credential files."""

    @pytest.mark.parametrize(
        ("filename", "rel_path"),
        [
            (".env", ".env"),
            (".env.local", ".env.local"),
            (".env.production", "config/.env.production"),
            ("id_rsa", "keys/id_rsa"),
            ("id_rsa.pub", "id_rsa.pub"),
            ("id_ed25519", ".ssh/id_ed25519"),
            ("credentials.json", "credentials.json"),
            ("service-account.json", "auth/service-account.json"),
            ("service_account.json", "service_account.json"),
            ("server.key", "ssl/server.key"),
            ("cert.pem", "ssl/cert.pem"),
            ("keystore.p12", "certs/keystore.p12"),
            ("secrets.yaml", "secrets.yaml"),
        ],
    )
    def test_secret_files_detected(self, filename: str, rel_path: str) -> None:
        assert is_secret_file(filename, rel_path) is True

    @pytest.mark.parametrize(
        ("filename", "rel_path"),
        [
            ("main.py", "main.py"),
            ("config.py", "src/config.py"),
            ("settings.json", "settings.json"),
            ("README.md", "README.md"),
            (".gitignore", ".gitignore"),
            (".eslintrc.json", ".eslintrc.json"),
            ("environment.ts", "src/environment.ts"),
            ("key_handler.py", "app/key_handler.py"),
        ],
    )
    def test_safe_files_not_detected_as_secrets(
        self, filename: str, rel_path: str
    ) -> None:
        assert is_secret_file(filename, rel_path) is False


class TestBinaryContentDetection:
    """Verify binary content detection logic."""

    def test_plain_text_file(self, tmp_path: Path) -> None:
        text_file = tmp_path / "hello.py"
        text_file.write_text("def hello():\n    print('world')\n", encoding="utf-8")
        assert is_binary_content(text_file) is False

    def test_null_byte_detected_as_binary(self, tmp_path: Path) -> None:
        binary_file = tmp_path / "data.bin"
        binary_file.write_bytes(b"some header\x00\x01\x02\x03more binary data")
        assert is_binary_content(binary_file) is True

    def test_empty_file_not_binary(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.txt"
        empty_file.write_bytes(b"")
        assert is_binary_content(empty_file) is False


class TestFileFilterPolicy:
    """Verify overall FileFilterPolicy evaluation."""

    def test_ignored_directories(self) -> None:
        policy = FileFilterPolicy()
        assert policy.should_ignore_directory(".git") is True
        assert policy.should_ignore_directory("node_modules") is True
        assert policy.should_ignore_directory("__pycache__") is True
        assert policy.should_ignore_directory(".venv") is True
        assert policy.should_ignore_directory("dist") is True
        assert policy.should_ignore_directory("build") is True
        assert policy.should_ignore_directory("coverage") is True
        assert policy.should_ignore_directory(".idea") is True
        assert policy.should_ignore_directory(".vscode") is True
        assert policy.should_ignore_directory(".next") is True
        # Non-ignored directory
        assert policy.should_ignore_directory("src") is False
        assert policy.should_ignore_directory("tests") is False
        assert policy.should_ignore_directory("app") is False

    def test_accepted_source_file(self, tmp_path: Path) -> None:
        policy = FileFilterPolicy()
        src_file = tmp_path / "app.py"
        src_file.write_text("import sys\nprint('ok')\n", encoding="utf-8")
        ignored, reason = policy.evaluate_file(src_file, "app.py")
        assert ignored is False
        assert reason is None

    def test_ignored_binary_extension(self, tmp_path: Path) -> None:
        policy = FileFilterPolicy()
        bin_file = tmp_path / "app.exe"
        bin_file.write_bytes(b"fake-exe-content")
        ignored, reason = policy.evaluate_file(bin_file, "app.exe")
        assert ignored is True
        assert reason == "binary_extension"

    def test_ignored_secret_file(self, tmp_path: Path) -> None:
        policy = FileFilterPolicy()
        secret_file = tmp_path / ".env"
        secret_file.write_text("SECRET=123\n", encoding="utf-8")
        ignored, reason = policy.evaluate_file(secret_file, ".env")
        assert ignored is True
        assert reason == "secret_or_credential_file"

    def test_oversized_file_ignored(self, tmp_path: Path) -> None:
        policy = FileFilterPolicy(max_single_file_size=100)
        large_file = tmp_path / "huge.txt"
        large_file.write_bytes(b"x" * 200)
        ignored, reason = policy.evaluate_file(large_file, "huge.txt")
        assert ignored is True
        assert reason is not None and "file_size_exceeded" in reason
