"""migrate embeddings to voyage-code-4 (1536 -> 1024 dimensions)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18 00:00:00.000000

Anthropic does not provide its own embedding model and recommends Voyage
AI; CodeSage's embedding provider is moving from a 1536-dimensional
OpenAI-shaped vector (in practice only ever exercised by
MockEmbeddingProvider so far) to Voyage's ``voyage-code-4`` model at its
default 1024-dimensional output. This migration resizes
``code_chunks.embedding`` accordingly and recreates its HNSW index.

Any existing embedding is explicitly invalidated (set to NULL) before the
column's type changes -- not only because a 1536-dim vector cannot be cast
to 1024-dim, but because pre-existing mock/OpenAI-shaped embeddings must
never be silently treated as valid real embeddings regardless of
dimension. Affected repositories must be re-indexed (re-run
``POST /repositories/{id}/ingest``) after this migration to get real
Voyage embeddings populated again.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name == "postgresql":
        # 1. Drop the HNSW index first -- it's built over the current
        #    1536-dim column and must not exist while the column's type
        #    changes underneath it.
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_hnsw;")

        # 2. Invalidate every existing embedding BEFORE the type change.
        #    A 1536-dim vector cannot be cast to 1024-dim (pgvector has no
        #    such cast), and pre-existing mock/OpenAI-shaped embeddings
        #    must never be silently treated as valid real embeddings
        #    regardless of dimension -- so this is an explicit correctness
        #    step, not merely a side effect of the type change. In
        #    production code_chunks currently has 0 rows (no repository
        #    has been ingested yet), so this is a no-op there, but must
        #    still be correct for any local/dev/CI database that already
        #    has mock-embedded rows.
        op.execute("UPDATE code_chunks SET embedding = NULL;")

        # 3. Change the column's vector width. pgvector type changes are
        #    not a first-class Alembic op -- raw SQL, as this repo already
        #    does for the vector extension / tsvector column / HNSW index
        #    in migration 0004.
        op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(1024);")

        # 4. Recreate the HNSW index identically to migration 0004, now
        #    over the resized column.
        op.execute(
            "CREATE INDEX ix_code_chunks_embedding_hnsw "
            "ON code_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64);"
        )
    # tsv_content / ix_code_chunks_tsv (full-text search) are untouched --
    # this migration only changes the vector column and its own index.


def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name == "postgresql":
        # This downgrade is inherently lossy: 1024-dim vectors cannot be
        # cast back into meaningful 1536-dim vectors (there is no inverse
        # of the original embedding, and no record of it). Every embedding
        # is discarded (again) on the way down, exactly as on the way up --
        # this restores the *schema* shape from before this migration, not
        # the embedding *data*, which was already being invalidated by
        # design. Any repository embedded under the 1024-dim schema will
        # need to be re-ingested after a downgrade, same as it would after
        # this migration's own upgrade.
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_hnsw;")
        op.execute("UPDATE code_chunks SET embedding = NULL;")
        op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(1536);")
        op.execute(
            "CREATE INDEX ix_code_chunks_embedding_hnsw "
            "ON code_chunks USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64);"
        )
