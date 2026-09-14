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

    def test_settings_rejects_debug_true_in_production(self) -> None:
        """DEBUG=true must never be combined with APP_ENV=production."""
        with pytest.raises(ValidationError, match="DEBUG=true is not allowed"):
            Settings(
                SECRET_KEY="a" * 32,
                DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
                APP_ENV=AppEnvironment.PRODUCTION,
                DEBUG=True,
            )

    def test_settings_allows_debug_true_outside_production(self) -> None:
        """DEBUG=true stays allowed for development/staging."""
        settings = Settings(
            SECRET_KEY="a" * 32,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
            APP_ENV=AppEnvironment.STAGING,
            DEBUG=True,
        )
        assert settings.DEBUG is True

    def test_settings_allows_debug_false_in_production(self) -> None:
        """DEBUG=false is the only allowed pairing with APP_ENV=production."""
        settings = Settings(
            SECRET_KEY="a" * 32,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
            APP_ENV=AppEnvironment.PRODUCTION,
            DEBUG=False,
        )
        assert settings.APP_ENV == AppEnvironment.PRODUCTION

    def test_settings_registration_enabled_defaults_true(self) -> None:
        """Registration stays open by default -- an operator opts out, not in."""
        settings = Settings(
            SECRET_KEY="a" * 32,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        )
        assert settings.REGISTRATION_ENABLED is True

    def test_settings_db_pool_defaults(self) -> None:
        """Pool settings default to conservative values safe for pooled DSNs."""
        settings = Settings(
            SECRET_KEY="a" * 32,
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        )
        assert settings.DB_POOL_SIZE == 5
        assert settings.DB_MAX_OVERFLOW == 5
        assert settings.DB_STATEMENT_CACHE_SIZE == 100
