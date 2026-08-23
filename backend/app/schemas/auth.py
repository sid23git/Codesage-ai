"""Pydantic schemas for authentication tokens and claims."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """Schema returned upon successful authentication containing the JWT."""

    access_token: str = Field(description="Signed JWT access token.")
    token_type: str = Field(
        default="bearer", description="Token type (always 'bearer')."
    )


class TokenPayload(BaseModel):
    """Schema representing validated claims decoded from a JWT access token."""

    sub: str = Field(description="Subject identifier (user ID).")
    exp: int | None = Field(default=None, description="Expiration timestamp.")
    type: str = Field(default="access", description="Token type.")
