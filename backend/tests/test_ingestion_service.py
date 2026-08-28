"""Unit and integration tests for IngestionService lifecycle and persistence."""

from __future__ import annotations

import io
import tarfile
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.github.client import GitHubClient
from app.github.exceptions import (
    GitHubRateLimitError,
    GitHubRepositoryNotFoundError,
)
from app.models.user import User
from app.schemas.ingestion import IngestionStatus
from app.schemas.repository import RepositoryCreate
from app.services.ingestion_service import IngestionService
from app.services.repository_service import RepositoryService


def _create_mock_tarball(files: dict[str, bytes]) -> bytes:
    """Create in-memory tarball for testing."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def mock_tarball_bytes() -> bytes:
    return _create_mock_tarball(
        {
            "octocat-hello-world-e9a8f7c/main.py": (
                b"def main():\n    print('Codesage')\n"
            ),
            "octocat-hello-world-e9a8f7c/README.md": b"# Codesage AI\n",
            "octocat-hello-world-e9a8f7c/src/core.py": b"class Core:\n    pass\n",
        }
    )


class TestIngestionServiceSuccess:
    """Verify happy path ingestion pipeline."""

    async def test_trigger_ingestion_success(
        self,
        db_session: AsyncSession,
        test_user: User,
        mock_tarball_bytes: bytes,
    ) -> None:
        # 1. Create a repository
        repo_in = RepositoryCreate(
            name="Hello-World",
            github_url="https://github.com/octocat/Hello-World",
        )
        repo = await RepositoryService.create_repository(
            db_session, test_user.id, repo_in
        )
        await db_session.commit()

        # 2. Mock GitHubClient
        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.return_value = mock_tarball_bytes

        # 3. Trigger ingestion
        ingestion = await IngestionService.trigger_ingestion(
            db_session, test_user.id, repo.id, mock_github
        )

        assert ingestion is not None
        assert ingestion.status == IngestionStatus.COMPLETED.value
        assert ingestion.commit_sha == "e9a8f7c"
        assert ingestion.file_count == 3
        assert ingestion.total_size_bytes > 0
        assert ingestion.total_lines > 0
        assert ingestion.primary_language == "Python"
        assert ingestion.language_stats is not None
        assert "Python" in ingestion.language_stats
        assert "Markdown" in ingestion.language_stats
        assert ingestion.file_catalog is not None
        assert len(ingestion.file_catalog) == 3
        assert ingestion.started_at is not None
        assert ingestion.completed_at is not None
        assert ingestion.error_message is None

        # Verify repository was updated
        updated_repo = await RepositoryService.get_repository(
            db_session, test_user.id, repo.id
        )
        assert updated_repo is not None
        assert updated_repo.status == "ready"
        assert updated_repo.primary_language == "Python"


class TestIngestionServiceFailures:
    """Verify error handling, status updates, and user-safe messages."""

    async def test_github_not_found_sets_failed_status(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        repo_in = RepositoryCreate(
            name="Missing-Repo",
            github_url="https://github.com/octocat/Missing-Repo",
        )
        repo = await RepositoryService.create_repository(
            db_session, test_user.id, repo_in
        )
        await db_session.commit()

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.side_effect = GitHubRepositoryNotFoundError(
            "Repository not found."
        )

        with pytest.raises(GitHubRepositoryNotFoundError):
            await IngestionService.trigger_ingestion(
                db_session, test_user.id, repo.id, mock_github
            )

        # Ingestion record should exist in failed state
        latest = await IngestionService.get_latest_ingestion(
            db_session, test_user.id, repo.id
        )
        assert latest is not None
        assert latest.status == IngestionStatus.FAILED.value
        assert "not found" in (latest.error_message or "").lower()

        # Repository should be in failed state
        updated_repo = await RepositoryService.get_repository(
            db_session, test_user.id, repo.id
        )
        assert updated_repo is not None
        assert updated_repo.status == "failed"

    async def test_rate_limit_sets_failed_status(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        repo_in = RepositoryCreate(
            name="Rate-Limit-Repo",
            github_url="https://github.com/octocat/Rate-Limit-Repo",
        )
        repo = await RepositoryService.create_repository(
            db_session, test_user.id, repo_in
        )
        await db_session.commit()

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.side_effect = GitHubRateLimitError(
            "GitHub API rate limit exceeded."
        )

        with pytest.raises(GitHubRateLimitError):
            await IngestionService.trigger_ingestion(
                db_session, test_user.id, repo.id, mock_github
            )

        latest = await IngestionService.get_latest_ingestion(
            db_session, test_user.id, repo.id
        )
        assert latest is not None
        assert latest.status == IngestionStatus.FAILED.value
        assert "rate limit" in (latest.error_message or "").lower()


class TestIngestionQueryAndIsolation:
    """Verify querying ingestion history and ownership boundaries."""

    async def test_get_latest_and_list_ingestions(
        self,
        db_session: AsyncSession,
        test_user: User,
        other_user: User,
        mock_tarball_bytes: bytes,
    ) -> None:
        repo_in = RepositoryCreate(
            name="Multi-Ingest-Repo",
            github_url="https://github.com/octocat/Multi-Ingest-Repo",
        )
        repo = await RepositoryService.create_repository(
            db_session, test_user.id, repo_in
        )
        await db_session.commit()

        mock_github = AsyncMock(spec=GitHubClient)
        mock_github.download_tarball.return_value = mock_tarball_bytes

        # First ingestion
        ingestion_1 = await IngestionService.trigger_ingestion(
            db_session, test_user.id, repo.id, mock_github
        )
        assert ingestion_1 is not None

        # Second ingestion
        ingestion_2 = await IngestionService.trigger_ingestion(
            db_session, test_user.id, repo.id, mock_github
        )
        assert ingestion_2 is not None

        # List should return 2 records
        all_ingestions = await IngestionService.list_ingestions(
            db_session, test_user.id, repo.id
        )
        assert all_ingestions is not None
        assert len(all_ingestions) == 2

        # Latest should be ingestion_2
        latest = await IngestionService.get_latest_ingestion(
            db_session, test_user.id, repo.id
        )
        assert latest is not None
        assert latest.id == ingestion_2.id

        # Other user cannot access
        other_latest = await IngestionService.get_latest_ingestion(
            db_session, other_user.id, repo.id
        )
        assert other_latest is None

        other_list = await IngestionService.list_ingestions(
            db_session, other_user.id, repo.id
        )
        assert other_list is None
