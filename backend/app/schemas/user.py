"""Pydantic schemas for user registration, authentication, and responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Schema for user registration request."""

    email: EmailStr = Field(description="User's primary email address.")
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plaintext password (minimum 8 characters).",
    )


class UserLogin(BaseModel):
    """Schema for user login request."""

    email: EmailStr = Field(description="User's registered email address.")
    password: str = Field(
        min_length=1,
        description="User password.",
    )


class UserResponse(BaseModel):
    """Safe schema for user details returned by API endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
