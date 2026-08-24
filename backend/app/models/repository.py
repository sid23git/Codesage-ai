"""Repository SQLAlchemy ORM model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Repository(Base):
    """Repository entity.

    Represents a code repository tracked and analyzed by CodeSage AI,
    owned by a specific user.

    GitHub metadata columns (``github_repository_id`` through
    ``last_synced_at``) are nullable and populated only after a successful
    sync via ``POST /repositories/{id}/sync``.
    """

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "github_url", name="uq_user_repository_github_url"
        ),
    )

    # ── Core identity ──────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(512), nullable=False)
    github_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_language: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)

    # ── GitHub metadata (populated after first sync) ───────────────────────────
    github_repository_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        unique=True,
        index=True,
        comment="GitHub's numeric repository ID.",
    )
    github_owner: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="GitHub owner (user or organisation) login.",
    )
    default_branch: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Default branch name reported by GitHub (e.g. 'main').",
    )
    stars: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="GitHub stargazers count at last sync.",
    )
    forks: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="GitHub forks count at last sync.",
    )
    open_issues: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="GitHub open issues count at last sync.",
    )
    github_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="GitHub's own 'updated_at' timestamp at last sync.",
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the most recent successful sync from GitHub.",
    )

    # ── Record timestamps ──────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    owner: Mapped[User] = relationship("User", back_populates="repositories")

    def __repr__(self) -> str:
        return (
            f"<Repository id={self.id} full_name={self.full_name!r} "
            f"owner_id={self.owner_id} status={self.status!r}>"
        )
