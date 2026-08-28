"""Tests for application settings and configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import AppEnvironment, LogLevel, Settings


class TestSettings:
    """Test suite for Settings model validation and DSN resolution."""

    def test_settings_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings should populate defaults cleanly.

        ``_env_file=None`` suppresses loading of the local developer ``.env``
        file so that this test always measures pure field defaults, regardless
        of what overrides the developer may have on disk.
        """
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        )
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.APP_NAME == "codesage-api"
        assert settings.APP_ENV == AppEnvironment.DEVELOPMENT
        assert settings.DEBUG is False
        assert settings.LOG_LEVEL == LogLevel.INFO
        assert (
            settings.async_database_url
            == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        )

    def test_settings_construct_dsn_from_components(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Settings should assemble async DSN from DB_* components."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        settings = Settings(
            SECRET_KEY="a" * 32,
            DATABASE_URL=None,
            DB_HOST="db.internal",
            DB_PORT=5433,
            DB_NAME="mydb",
            DB_USER="myuser",
            DB_PASSWORD="mypassword",
        )
        expected_url = "postgresql+asyncpg://myuser:mypassword@db.internal:5433/mydb"
        assert settings.async_database_url == expected_url

    def test_settings_rejects_non_asyncpg_database_url(self) -> None:
        """Settings should reject DATABASE_URL without postgresql+asyncpg://."""
        with pytest.raises(ValidationError, match="asyncpg driver scheme"):
            Settings(
                SECRET_KEY="a" * 32,
                DATABASE_URL="postgresql://user:pass@localhost:5432/testdb",
            )

    def test_settings_rejects_missing_password_when_no_database_url(self) -> None:
        """Settings should reject empty DB_PASSWORD when DATABASE_URL is omitted."""
        with pytest.raises(ValidationError, match="DB_PASSWORD must be set"):
            Settings(
                SECRET_KEY="a" * 32,
                DATABASE_URL=None,
                DB_PASSWORD="",
            )

    def test_settings_rejects_placeholder_secret_key(self) -> None:
        """Settings should reject placeholder SECRET_KEY values."""
        with pytest.raises(
            ValidationError, match="SECRET_KEY is set to a placeholder value"
        ):
            Settings(
                SECRET_KEY="change-me-before-deploying-to-any-real-environment",
                DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
            )

    def test_settings_rejects_short_secret_key(self) -> None:
        """Settings should reject SECRET_KEY shorter than 32 characters."""
        with pytest.raises(ValidationError):
            Settings(
                SECRET_KEY="too-short",
                DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
            )
