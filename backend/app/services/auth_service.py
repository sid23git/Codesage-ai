"""Authentication and user management business logic."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)


class UserAlreadyExistsError(Exception):
    """Raised when attempting to register a user with an email already in use."""


class AuthService:
    """Service layer handling user lifecycle and credential validation."""

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
        """Fetch a single user by primary key.

        Parameters
        ----------
        db:
            Database async session.
        user_id:
            User primary key ID.

        Returns
        -------
        User | None
            The User instance if found, None otherwise.
        """
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalars().first()

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
        """Fetch a single user by email address (case-insensitive).

        Parameters
        ----------
        db:
            Database async session.
        email:
            Email address string.

        Returns
        -------
        User | None
            The User instance if found, None otherwise.
        """
        normalized_email = email.strip().lower()
        result = await db.execute(select(User).where(User.email == normalized_email))
        return result.scalars().first()

    @classmethod
    async def register_user(cls, db: AsyncSession, user_in: UserCreate) -> User:
        """Register a new user account with hashed password.

        Parameters
        ----------
        db:
            Database async session.
        user_in:
            Validated registration request schema.

        Returns
        -------
        User
            The newly created and committed User instance.

        Raises
        ------
        UserAlreadyExistsError
            If a user with this email already exists.
        """
        normalized_email = user_in.email.strip().lower()
        existing_user = await cls.get_user_by_email(db, normalized_email)
        if existing_user is not None:
            logger.warning(
                "Registration rejected: email %s already exists", normalized_email
            )
            raise UserAlreadyExistsError(
                f"User with email '{normalized_email}' already exists."
            )

        hashed_pw = hash_password(user_in.password)
        new_user = User(
            email=normalized_email,
            password_hash=hashed_pw,
            is_active=True,
        )
        db.add(new_user)
        await db.flush()
        await db.refresh(new_user)
        logger.info(
            "New user registered successfully: id=%s email=%s",
            new_user.id,
            new_user.email,
        )
        return new_user

    @classmethod
    async def authenticate_user(
        cls, db: AsyncSession, email: str, password: str
    ) -> User | None:
        """Authenticate user by email and plaintext password.

        Parameters
        ----------
        db:
            Database async session.
        email:
            User email address.
        password:
            Plaintext password to verify.

        Returns
        -------
        User | None
            User instance on successful authentication, None on failure.
        """
        user = await cls.get_user_by_email(db, email)
        if user is None:
            return None

        if not user.is_active:
            logger.warning("Authentication failed: user id=%s is inactive", user.id)
            return None

        if not verify_password(password, user.password_hash):
            logger.warning(
                "Authentication failed: invalid password for user id=%s", user.id
            )
            return None

        return user
