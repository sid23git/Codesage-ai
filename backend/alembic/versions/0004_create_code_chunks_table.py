"""create_code_chunks_table

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-29 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # We must ensure the vector extension exists on postgresql
    bind = op.get_bind()
    if bind.engine.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        'code_chunks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('ingestion_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=1024), nullable=False),
        sa.Column('language', sa.String(length=100), nullable=True),
        sa.Column('chunk_type', sa.String(length=50), server_default='block', nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('start_line', sa.Integer(), nullable=False),
        sa.Column('end_line', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(dim=1536), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ingestion_id'], ['repository_ingestions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('ix_code_chunks_repo_file', 'code_chunks', ['repository_id', 'file_path'], unique=False)
    op.create_index('ix_code_chunks_repo_ingestion', 'code_chunks', ['repository_id', 'ingestion_id'], unique=False)
    op.create_index('ix_code_chunks_repo_name', 'code_chunks', ['repository_id', 'name'], unique=False)

    if bind.engine.name == "postgresql":
        # Add tsvector generated column and index
        op.execute("""
            ALTER TABLE code_chunks 
            ADD COLUMN tsv_content tsvector 
            GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(name, '') || ' ' || coalesce(file_path, '') || ' ' || chunk_text)
            ) STORED;
        """)
        op.execute("CREATE INDEX ix_code_chunks_tsv ON code_chunks USING GIN(tsv_content);")
        
        # Add HNSW index
        op.execute("""
            CREATE INDEX ix_code_chunks_embedding_hnsw 
            ON code_chunks USING hnsw (embedding vector_cosine_ops) 
            WITH (m = 16, ef_construction = 64);
        """)

def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_hnsw;")
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_tsv;")
        # No need to explicitly drop tsv_content column since we drop the table

    op.drop_index('ix_code_chunks_repo_name', table_name='code_chunks')
    op.drop_index('ix_code_chunks_repo_ingestion', table_name='code_chunks')
    op.drop_index('ix_code_chunks_repo_file', table_name='code_chunks')
    op.drop_table('code_chunks')
