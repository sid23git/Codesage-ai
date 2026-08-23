"""Application settings loaded from environment variables.

All configuration is sourced from the process environment or a `.env` file.
No passwords, keys, or credentials are ever hard-coded here.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Valid deployment environments."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Valid log-level values."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Application settings.

    Variables are read (in order of precedence):
    1. Process environment
    2. `.env` file in the working directory
    3. Default values defined here

    Database URL resolution
    -----------------------
    Supply either ``DATABASE_URL`` (a full DSN) **or** the individual
    ``DB_*`` variables.  ``DATABASE_URL`` takes precedence when both are
    present.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = Field(
        default="codesage-api", description="Human-readable service name."
    )
    APP_ENV: AppEnvironment = Field(
        default=AppEnvironment.DEVELOPMENT,
        description="Deployment environment.",
    )
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode (never True in production).",
    )
    LOG_LEVEL: LogLevel = Field(default=LogLevel.INFO, description="Root log level.")
    SECRET_KEY: str = Field(
        ...,
        min_length=32,
        description=(
            "Secret key used for signing tokens. Must be at least 32 characters."
        ),
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="Algorithm used for signing JWT access tokens.",
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=1440,
        gt=0,
        description="Access token lifespan in minutes (default 24 hours).",
    )

    # ------------------------------------------------------------------
    # Database — option A: full DSN
    # ------------------------------------------------------------------
    DATABASE_URL: str | None = Field(
        default=None,
        description=(
            "Full PostgreSQL DSN.  When set, DB_* variables are ignored.  "
            "Must use the asyncpg driver, e.g. "
            "postgresql+asyncpg://user:pass@host:5432/dbname"
        ),
    )

    # ------------------------------------------------------------------
    # Database — option B: individual components
    # ------------------------------------------------------------------
    DB_HOST: str = Field(default="localhost")
    DB_PORT: int = Field(default=5432)
    DB_NAME: str = Field(default="codesage")
    DB_USER: str = Field(default="codesage")
    DB_PASSWORD: str = Field(default="")

    # ------------------------------------------------------------------
    # Resolved DSN (populated by the model validator below)
    # ------------------------------------------------------------------
    _resolved_database_url: str = ""

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def secret_key_must_not_be_placeholder(cls, v: str) -> str:
        """Reject obvious placeholder values in non-dev environments."""
        if v in {"change-me-before-deploying-to-any-real-environment", ""}:
            raise ValueError(
                "SECRET_KEY is set to a placeholder value.  "
                "Generate a real secret with: "
                'python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v

    @model_validator(mode="after")
    def resolve_database_url(self) -> Settings:
        """Build the async DSN from individual DB_* vars when DATABASE_URL is absent."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if not url.startswith("postgresql+asyncpg://"):
                raise ValueError(
                    "DATABASE_URL must use the asyncpg driver scheme: "
                    "postgresql+asyncpg://<user>:<pass>@<host>:<port>/<dbname>"
                )
            self._resolved_database_url = url
        else:
            if not self.DB_PASSWORD:
                raise ValueError(
                    "DB_PASSWORD must be set (or supply a full DATABASE_URL)."
                )
            self._resolved_database_url = (
                f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        return self

    @property
    def async_database_url(self) -> str:
        """Return the resolved async-compatible database URL."""
        return self._resolved_database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Raises
    ------
    pydantic_core.ValidationError
        If required environment variables are missing or invalid.
    """
    return Settings()
