"""Security and cryptographic utilities for authentication and authorization.

Handles password hashing/verification using bcrypt and JWT token creation/decoding
using PyJWT.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt with a generated salt.

    Parameters
    ----------
    password:
        The raw plaintext password.

    Returns
    -------
    str
        The bcrypt-hashed password string.
    """
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Parameters
    ----------
    plain_password:
        The plaintext password to test.
    hashed_password:
        The stored bcrypt hash.

    Returns
    -------
    bool
        True if the password matches the hash, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def create_access_token(
    subject: str | int,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Generate a signed JWT access token.

    Parameters
    ----------
    subject:
        The subject of the token (typically user ID as string).
    expires_delta:
        Optional custom duration before expiration.
    extra_claims:
        Optional additional payload claims.

    Returns
    -------
    str
        Encoded JWT token string.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a signed JWT access token.

    Parameters
    ----------
    token:
        The encoded JWT token string.

    Returns
    -------
    dict[str, Any]
        Decoded payload claims.

    Raises
    ------
    jwt.ExpiredSignatureError
        If the token has expired.
    jwt.InvalidTokenError
        If the token is malformed, invalid, or signature does not match.
    """
    settings = get_settings()
    return jwt.decode(  # type: ignore[no-any-return]
        token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
