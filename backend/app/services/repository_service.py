"""Repository business logic and authorization enforcement."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from app.schemas.repository import RepositoryCreate, RepositoryStatus, RepositoryUpdate

logger = logging.getLogger(__name__)


class RepositoryAlreadyExistsError(Exception):
    """Raised when a user attempts to add a repository URL they already registered."""


def _extract_full_name(github_url: str, default_name: str) -> str:
    """Extract 'owner/repo' from a GitHub URL or fall back to default name."""
    try:
        parsed = urlparse(github_url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(path_parts) >= 2:
            org, repo = path_parts[0], path_parts[1]
            if repo.endswith(".git"):
                repo = repo[:-4]
            return f"{org}/{repo}"
    except (ValueError, AttributeError) as exc:
        logger.debug("Failed to extract full_name from url %s: %s", github_url, exc)
    return default_name


class RepositoryService:
    """Service layer managing repository records with strict ownership boundaries."""

    @staticmethod
    async def create_repository(
        db: AsyncSession, owner_id: int, repo_in: RepositoryCreate
    ) -> Repository:
        """Register a new repository for the authenticated user.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the user who owns this repository.
        repo_in:
            Validated creation schema.

        Returns
        -------
        Repository
            The newly created repository record.

        Raises
        ------
        RepositoryAlreadyExistsError
            If this user has already registered this github_url.
        """
        # Check duplicate for this owner
        existing = await db.execute(
            select(Repository).where(
                Repository.owner_id == owner_id,
                Repository.github_url == repo_in.github_url,
            )
        )
        if existing.scalars().first() is not None:
            raise RepositoryAlreadyExistsError(
                f"You have already added the repository at '{repo_in.github_url}'."
            )

        full_name = _extract_full_name(repo_in.github_url, repo_in.name)

        repo = Repository(
            owner_id=owner_id,
            name=repo_in.name,
            full_name=full_name,
            github_url=repo_in.github_url,
            description=repo_in.description,
            primary_language=repo_in.primary_language,
            status=RepositoryStatus.PENDING.value,
        )
        db.add(repo)
        await db.flush()
        await db.refresh(repo)
        logger.info(
            "Repository created: id=%s full_name=%s owner_id=%s",
            repo.id,
            repo.full_name,
            owner_id,
        )
        return repo

    @staticmethod
    async def list_repositories(db: AsyncSession, owner_id: int) -> list[Repository]:
        """List all repositories belonging to the specified owner.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            User ID to filter by.

        Returns
        -------
        list[Repository]
            List of repository entities owned by the user.
        """
        result = await db.execute(
            select(Repository)
            .where(Repository.owner_id == owner_id)
            .order_by(Repository.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_repository(
        db: AsyncSession, owner_id: int, repository_id: int
    ) -> Repository | None:
        """Fetch a repository by ID, strictly scoped to its owner.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the requesting user.
        repository_id:
            Target repository primary key.

        Returns
        -------
        Repository | None
            The repository if found and owned by the user, None otherwise.
        """
        result = await db.execute(
            select(Repository).where(
                Repository.id == repository_id,
                Repository.owner_id == owner_id,
            )
        )
        return result.scalars().first()

    @classmethod
    async def update_repository(
        cls,
        db: AsyncSession,
        owner_id: int,
        repository_id: int,
        repo_update: RepositoryUpdate,
    ) -> Repository | None:
        """Update repository metadata with ownership verification.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the requesting user.
        repository_id:
            Target repository primary key.
        repo_update:
            Validated fields to update.

        Returns
        -------
        Repository | None
            Updated repository if found and owned, None otherwise.
        """
        repo = await cls.get_repository(db, owner_id, repository_id)
        if repo is None:
            return None

        update_data = repo_update.model_dump(exclude_unset=True)
        for field_name, value in update_data.items():
            if field_name == "status" and value is not None:
                setattr(repo, field_name, getattr(value, "value", str(value)))
            elif value is not None:
                setattr(repo, field_name, value)

        await db.flush()
        await db.refresh(repo)
        logger.info("Repository updated: id=%s owner_id=%s", repository_id, owner_id)
        return repo

    @classmethod
    async def delete_repository(
        cls, db: AsyncSession, owner_id: int, repository_id: int
    ) -> bool:
        """Delete a repository with ownership verification.

        Parameters
        ----------
        db:
            Database async session.
        owner_id:
            ID of the requesting user.
        repository_id:
            Target repository primary key.

        Returns
        -------
        bool
            True if deleted, False if repository not found or not owned.
        """
        repo = await cls.get_repository(db, owner_id, repository_id)
        if repo is None:
            return False

        await db.delete(repo)
        await db.flush()
        logger.info("Repository deleted: id=%s owner_id=%s", repository_id, owner_id)
        return True
