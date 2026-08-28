"""Repository API endpoints for managing user code repositories."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_github_client
from app.db.session import get_db
from app.github.client import GitHubClient
from app.github.exceptions import (
    GitHubArchiveSizeExceededError,
    GitHubMalformedResponseError,
    GitHubRateLimitError,
    GitHubRepositoryNotFoundError,
    GitHubTimeoutError,
    GitHubUpstreamError,
    InvalidGitHubURLError,
)
from app.ingestion.exceptions import (
    ArchiveExtractionError,
    IngestionError,
    IngestionLimitExceededError,
    SecurityViolationError,
)
from app.models.user import User
from app.schemas.ingestion import (
    IngestionResponse,
    IngestionSummaryResponse,
)
from app.schemas.repository import (
    RepositoryCreate,
    RepositoryResponse,
    RepositoryUpdate,
)
from app.services.ingestion_service import IngestionService
from app.services.repository_service import (
    RepositoryAlreadyExistsError,
    RepositoryService,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a repository",
    description="Add a new repository to CodeSage AI for the current user.",
)
async def create_repository(
    repo_in: RepositoryCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepositoryResponse:
    """Create a new repository record owned by the authenticated user."""
    try:
        repo = await RepositoryService.create_repository(db, current_user.id, repo_in)
    except RepositoryAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return RepositoryResponse.model_validate(repo)


@router.get(
    "",
    response_model=list[RepositoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List user repositories",
    description="Retrieve all repositories owned by the currently authenticated user.",
)
async def list_repositories(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[RepositoryResponse]:
    """Return all repositories belonging to the current user."""
    repos = await RepositoryService.list_repositories(db, current_user.id)
    return [RepositoryResponse.model_validate(r) for r in repos]


@router.get(
    "/{repository_id}",
    response_model=RepositoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get repository details",
    description="Retrieve a specific repository by ID, ensuring owner authorization.",
)
async def get_repository(
    repository_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepositoryResponse:
    """Return a single repository if owned by the current user."""
    repo = await RepositoryService.get_repository(db, current_user.id, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    return RepositoryResponse.model_validate(repo)


@router.put(
    "/{repository_id}",
    response_model=RepositoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update repository metadata",
    description="Modify repository details if owned by the current user.",
)
async def update_repository(
    repository_id: int,
    repo_update: RepositoryUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepositoryResponse:
    """Update metadata of an owned repository."""
    repo = await RepositoryService.update_repository(
        db, current_user.id, repository_id, repo_update
    )
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    return RepositoryResponse.model_validate(repo)


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a repository",
    description="Delete a repository if owned by the current user.",
)
async def delete_repository(
    repository_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a repository belonging to the current user."""
    deleted = await RepositoryService.delete_repository(
        db, current_user.id, repository_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )


@router.post(
    "/{repository_id}/sync",
    response_model=RepositoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Sync repository from GitHub",
    description=(
        "Fetch public metadata from the GitHub API and persist it on the "
        "repository record.  Sets status to 'ready' on success or 'failed' "
        "on GitHub error.  The caller must be the repository owner."
    ),
)
async def sync_repository(
    repository_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    github_client: Annotated[GitHubClient, Depends(get_github_client)],
) -> RepositoryResponse:
    """Synchronize GitHub metadata for an owned repository.

    Raises HTTP errors mapped from GitHub integration exceptions:

    - ``InvalidGitHubURLError``       → 400 Bad Request
    - ``GitHubRepositoryNotFoundError`` → 404 Not Found
    - ``GitHubRateLimitError``        → 429 Too Many Requests
    - ``GitHubTimeoutError``          → 504 Gateway Timeout
    - ``GitHubUpstreamError``         → 502 Bad Gateway
    - ``GitHubMalformedResponseError`` → 502 Bad Gateway
    """
    try:
        repo = await RepositoryService.sync_repository(
            db, current_user.id, repository_id, github_client
        )
    except InvalidGitHubURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except GitHubRepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except GitHubRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except GitHubTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except (GitHubUpstreamError, GitHubMalformedResponseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    return RepositoryResponse.model_validate(repo)


@router.post(
    "/{repository_id}/ingest",
    response_model=IngestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest repository source",
    description=(
        "Retrieve repository source archive from GitHub, scan and filter files, "
        "detect languages, calculate structural metrics, and persist the "
        "ingestion result. Caller must be the repository owner."
    ),
)
async def ingest_repository(
    repository_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    github_client: Annotated[GitHubClient, Depends(get_github_client)],
) -> IngestionResponse:
    """Trigger full repository source ingestion and analysis."""
    try:
        ingestion = await IngestionService.trigger_ingestion(
            db, current_user.id, repository_id, github_client
        )
    except InvalidGitHubURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except GitHubRepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except GitHubRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except GitHubTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except GitHubArchiveSizeExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except SecurityViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except IngestionLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except ArchiveExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (GitHubUpstreamError, GitHubMalformedResponseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except IngestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if ingestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    return IngestionResponse.model_validate(ingestion)


@router.get(
    "/{repository_id}/ingestion",
    response_model=IngestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get latest repository ingestion",
    description=(
        "Retrieve the most recent ingestion record and structural metrics "
        "for an owned repository."
    ),
)
async def get_latest_ingestion(
    repository_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestionResponse:
    """Return the most recent ingestion run for the repository."""
    ingestion = await IngestionService.get_latest_ingestion(
        db, current_user.id, repository_id
    )
    if ingestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion record not found for this repository",
        )
    return IngestionResponse.model_validate(ingestion)


@router.get(
    "/{repository_id}/ingestions",
    response_model=list[IngestionSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List repository ingestions",
    description="Retrieve all historical ingestion records for an owned repository.",
)
async def list_ingestions(
    repository_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[IngestionSummaryResponse]:
    """Return historical ingestion runs for the repository."""
    ingestions = await IngestionService.list_ingestions(
        db, current_user.id, repository_id
    )
    if ingestions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    return [IngestionSummaryResponse.model_validate(i) for i in ingestions]


@router.get(
    "/{repository_id}/ingestions/{ingestion_id}",
    response_model=IngestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get repository ingestion by ID",
    description="Retrieve a specific ingestion record by ID for an owned repository.",
)
async def get_ingestion_by_id(
    repository_id: int,
    ingestion_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestionResponse:
    """Return a specific ingestion record for the repository."""
    ingestion = await IngestionService.get_ingestion(
        db, current_user.id, repository_id, ingestion_id
    )
    if ingestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion record not found",
        )
    return IngestionResponse.model_validate(ingestion)
