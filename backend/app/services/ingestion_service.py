"""Repository ingestion orchestration service."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.github.client import GitHubClient
from app.github.exceptions import GitHubIntegrationError
from app.github.url_parser import parse_github_url
from app.ingestion.archive import safe_extract_tarball
from app.ingestion.exceptions import (
    IngestionError,
)
from app.ingestion.filter import FileFilterPolicy
from app.ingestion.scanner import RepositoryScanner
from app.models.ingestion import RepositoryIngestion
from app.schemas.ingestion import IngestionStatus
from app.schemas.repository import RepositoryStatus
from app.services.repository_service import RepositoryService

logger = logging.getLogger(__name__)


def _force_remove_readonly(func: object, path: str, excinfo: object) -> None:
    """Error handler for ``shutil.rmtree`` to clear read-only files on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)
    except OSError:
        pass


def _cleanup_dir(dir_path: str | Path | None) -> None:
    """Safely remove a temporary directory and its contents."""
    if dir_path and os.path.exists(dir_path):
        try:
            shutil.rmtree(dir_path, onerror=_force_remove_readonly)
        except OSError as exc:
            logger.warning(
                "Failed to clean up temporary directory %s: %s", dir_path, exc
            )


class IngestionService:
    """Service layer orchestrating repository ingestion and analysis."""

    @classmethod
    async def trigger_ingestion(
        cls,
        db: AsyncSession,
        owner_id: int,
        repository_id: int,
        github_client: GitHubClient,
        settings: Settings | None = None,
    ) -> RepositoryIngestion | None:
        """Trigger a complete ingestion pipeline for an owned repository.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the user requesting ingestion (ownership check).
        repository_id:
            Repository primary key.
        github_client:
            Configured GitHub API client.
        settings:
            Application settings with configurable ingestion limits.

        Returns
        -------
        RepositoryIngestion | None
            Completed ingestion record, or None if repository not found / not owned.

        Raises
        ------
        InvalidGitHubURLError
            If repository URL is malformed or not a valid GitHub repo.
        GitHubRepositoryNotFoundError
            If repository does not exist on GitHub (404).
        GitHubRateLimitError
            If GitHub API rate limit is exceeded.
        GitHubTimeoutError
            If request times out.
        GitHubArchiveSizeExceededError
            If archive exceeds maximum size limit.
        SecurityViolationError
            If archive contains path traversal or symlink escapes.
        ArchiveExtractionError
            If archive is corrupt or triggers bomb defenses.
        IngestionLimitExceededError
            If file count or repo size exceeds limits.
        """
        app_settings = settings or get_settings()
        repo = await RepositoryService.get_repository(db, owner_id, repository_id)
        if repo is None:
            return None

        # Validate URL and extract coordinates
        coords = parse_github_url(repo.github_url)

        # Create initial ingestion record
        now = datetime.now(UTC)
        ingestion = RepositoryIngestion(
            repository_id=repo.id,
            status=IngestionStatus.INGESTING.value,
            started_at=now,
        )
        db.add(ingestion)
        repo.status = RepositoryStatus.ANALYZING.value
        await db.commit()
        await db.refresh(ingestion)
        await db.refresh(repo)

        temp_dir: str | None = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="codesage_ingest_")

            # 1. Download archive from GitHub
            archive_bytes = await github_client.download_tarball(
                owner=coords.owner,
                repo=coords.repo,
                ref=repo.default_branch,
                max_bytes=app_settings.INGESTION_MAX_ARCHIVE_SIZE_BYTES,
            )

            # 2. Safely extract archive to temp directory
            source_root, commit_sha = safe_extract_tarball(
                archive_bytes=archive_bytes,
                destination_dir=Path(temp_dir),
                max_uncompressed_bytes=app_settings.INGESTION_MAX_REPO_SIZE_BYTES,
                max_files=app_settings.INGESTION_MAX_FILE_COUNT,
            )

            # 3. Scan repository source files & extract structure
            filter_policy = FileFilterPolicy(
                max_single_file_size=app_settings.INGESTION_MAX_SINGLE_FILE_SIZE_BYTES
            )
            scanner = RepositoryScanner(
                filter_policy=filter_policy,
                max_file_count=app_settings.INGESTION_MAX_FILE_COUNT,
                max_repo_size_bytes=app_settings.INGESTION_MAX_REPO_SIZE_BYTES,
            )
            scan_result = scanner.scan_repository(source_root)

            # 4. Persist successful results
            ingestion.status = IngestionStatus.COMPLETED.value
            ingestion.commit_sha = commit_sha
            ingestion.file_count = scan_result.file_count
            ingestion.total_size_bytes = scan_result.total_size_bytes
            ingestion.total_lines = scan_result.total_lines
            ingestion.primary_language = (
                scan_result.primary_language or repo.primary_language
            )
            ingestion.language_stats = scan_result.language_stats
            ingestion.directory_summary = scan_result.directory_summary
            ingestion.file_catalog = scan_result.file_catalog
            ingestion.completed_at = datetime.now(UTC)
            ingestion.error_message = None

            # Update repository status & primary language if detected
            repo.status = RepositoryStatus.READY.value
            if scan_result.primary_language and not repo.primary_language:
                repo.primary_language = scan_result.primary_language

            await db.commit()
            await db.refresh(ingestion)
            await db.refresh(repo)
            logger.info(
                "Ingestion completed: repo_id=%s ingestion_id=%s files=%s size=%s",
                repo.id,
                ingestion.id,
                ingestion.file_count,
                ingestion.total_size_bytes,
            )
            return ingestion

        except (GitHubIntegrationError, IngestionError) as exc:
            logger.warning(
                "Ingestion failed for repo_id=%s (user-safe error): %s",
                repo.id,
                exc,
            )
            ingestion.status = IngestionStatus.FAILED.value
            ingestion.error_message = str(exc)
            ingestion.completed_at = datetime.now(UTC)
            repo.status = RepositoryStatus.FAILED.value
            await db.commit()
            await db.refresh(ingestion)
            await db.refresh(repo)
            raise

        except Exception:
            logger.exception("Unexpected error during ingestion of repo_id=%s", repo.id)
            ingestion.status = IngestionStatus.FAILED.value
            ingestion.error_message = (
                "An unexpected error occurred during repository ingestion."
            )
            ingestion.completed_at = datetime.now(UTC)
            repo.status = RepositoryStatus.FAILED.value
            await db.commit()
            await db.refresh(ingestion)
            await db.refresh(repo)
            raise

        finally:
            _cleanup_dir(temp_dir)

    @classmethod
    async def get_latest_ingestion(
        cls,
        db: AsyncSession,
        owner_id: int,
        repository_id: int,
    ) -> RepositoryIngestion | None:
        """Fetch the most recent ingestion record for an owned repository.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the requesting user (ownership check).
        repository_id:
            Target repository primary key.

        Returns
        -------
        RepositoryIngestion | None
            Latest ingestion record, or None if repo not owned or no ingestions exist.
        """
        repo = await RepositoryService.get_repository(db, owner_id, repository_id)
        if repo is None:
            return None

        result = await db.execute(
            select(RepositoryIngestion)
            .where(RepositoryIngestion.repository_id == repository_id)
            .order_by(
                RepositoryIngestion.created_at.desc(), RepositoryIngestion.id.desc()
            )
            .limit(1)
        )
        return result.scalars().first()

    @classmethod
    async def list_ingestions(
        cls,
        db: AsyncSession,
        owner_id: int,
        repository_id: int,
    ) -> list[RepositoryIngestion] | None:
        """List all ingestion records for an owned repository.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the requesting user (ownership check).
        repository_id:
            Target repository primary key.

        Returns
        -------
        list[RepositoryIngestion] | None
            List of ingestion records, or None if repo not found or not owned.
        """
        repo = await RepositoryService.get_repository(db, owner_id, repository_id)
        if repo is None:
            return None

        result = await db.execute(
            select(RepositoryIngestion)
            .where(RepositoryIngestion.repository_id == repository_id)
            .order_by(
                RepositoryIngestion.created_at.desc(), RepositoryIngestion.id.desc()
            )
        )
        return list(result.scalars().all())

    @classmethod
    async def get_ingestion(
        cls,
        db: AsyncSession,
        owner_id: int,
        repository_id: int,
        ingestion_id: int,
    ) -> RepositoryIngestion | None:
        """Fetch a specific ingestion record by ID with ownership verification.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the requesting user.
        repository_id:
            Target repository primary key.
        ingestion_id:
            Ingestion record primary key.

        Returns
        -------
        RepositoryIngestion | None
            Ingestion record if found and repository owned, None otherwise.
        """
        repo = await RepositoryService.get_repository(db, owner_id, repository_id)
        if repo is None:
            return None

        result = await db.execute(
            select(RepositoryIngestion).where(
                RepositoryIngestion.id == ingestion_id,
                RepositoryIngestion.repository_id == repository_id,
            )
        )
        return result.scalars().first()
