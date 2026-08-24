"""FastAPI request dependencies for authentication and database sessions."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.github.client import GitHubClient
from app.models.user import User
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# Security scheme requiring Bearer token in Authorization header
http_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Extract and validate the authenticated user from the Bearer JWT.

    Parameters
    ----------
    credentials:
        Bearer credentials from Authorization header.
    db:
        Database session.

    Returns
    -------
    User
        The authenticated active User entity.

    Raises
    ------
    HTTPException (401)
        If token is missing, invalid, expired, or user is inactive/not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if subject is None:
            raise credentials_exception
        user_id = int(subject)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except (InvalidTokenError, ValueError):
        raise credentials_exception from None

    user = await AuthService.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user account",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_github_client() -> GitHubClient:
    """Provide a configured ``GitHubClient`` instance as a FastAPI dependency.

    Reads ``GITHUB_TOKEN`` and ``GITHUB_REQUEST_TIMEOUT`` from the application
    settings.  Both values are optional/have defaults so no environment variable
    is strictly required.

    Returns
    -------
    GitHubClient
        A ready-to-use client instance.
    """
    settings = get_settings()
    return GitHubClient(
        token=settings.GITHUB_TOKEN,
        timeout=settings.GITHUB_REQUEST_TIMEOUT,
    )
