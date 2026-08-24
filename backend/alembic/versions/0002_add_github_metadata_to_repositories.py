"""add github metadata to repositories

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-24 00:00:00.000000

Adds eight nullable columns to the ``repositories`` table to store metadata
retrieved from the GitHub REST API after a successful sync.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # github_repository_id — GitHub's numeric repo ID (unique, indexed)
    op.add_column(
        "repositories",
        sa.Column("github_repository_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        op.f("ix_repositories_github_repository_id"),
        "repositories",
        ["github_repository_id"],
        unique=True,
    )

    # github_owner — owner login from GitHub
    op.add_column(
        "repositories",
        sa.Column("github_owner", sa.String(length=255), nullable=True),
    )

    # default_branch — e.g. "main"
    op.add_column(
        "repositories",
        sa.Column("default_branch", sa.String(length=255), nullable=True),
    )

    # stars / forks / open_issues — counters at last sync
    op.add_column(
        "repositories",
        sa.Column("stars", sa.Integer(), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("forks", sa.Integer(), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("open_issues", sa.Integer(), nullable=True),
    )

    # github_updated_at — GitHub's own updated_at for the repo
    op.add_column(
        "repositories",
        sa.Column("github_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # last_synced_at — when CodeSage last successfully synced this repo
    op.add_column(
        "repositories",
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("repositories", "last_synced_at")
    op.drop_column("repositories", "github_updated_at")
    op.drop_column("repositories", "open_issues")
    op.drop_column("repositories", "forks")
    op.drop_column("repositories", "stars")
    op.drop_column("repositories", "default_branch")
    op.drop_column("repositories", "github_owner")
    op.drop_index(
        op.f("ix_repositories_github_repository_id"), table_name="repositories"
    )
    op.drop_column("repositories", "github_repository_id")
