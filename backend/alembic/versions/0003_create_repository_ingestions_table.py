"""create repository_ingestions table

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27 00:00:00.000000

Creates the ``repository_ingestions`` table to persist ingestion run lifecycle
state, source revision, discovered file counts, total size, language breakdown,
directory structure, file catalog metadata, and user-safe error messages.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

json_type = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "repository_ingestions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column(
            "file_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_size_bytes",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_lines",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("primary_language", sa.String(length=100), nullable=True),
        sa.Column("language_stats", json_type, nullable=True),
        sa.Column("directory_summary", json_type, nullable=True),
        sa.Column("file_catalog", json_type, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name="fk_repository_ingestions_repository_id_repositories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_repository_ingestions_repository_id"),
        "repository_ingestions",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repository_ingestions_status"),
        "repository_ingestions",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_repository_ingestions_status"),
        table_name="repository_ingestions",
    )
    op.drop_index(
        op.f("ix_repository_ingestions_repository_id"),
        table_name="repository_ingestions",
    )
    op.drop_table("repository_ingestions")
