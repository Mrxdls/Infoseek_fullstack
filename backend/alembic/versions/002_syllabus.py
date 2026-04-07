"""Add syllabus table + pg_trgm + syllabus document_type

Revision ID: 002_syllabus
Revises: 001_gcp_pgvector
Create Date: 2026-04-05
"""

from alembic import op

revision = "002_syllabus"
down_revision = "001_gcp_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fuzzy text search extension
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Add 'syllabus' to documenttype enum
    op.execute("ALTER TYPE documenttype ADD VALUE IF NOT EXISTS 'syllabus'")

    op.execute("""
        CREATE TABLE syllabus (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            subject_code    VARCHAR(64),
            subject_name    VARCHAR(255) NOT NULL,
            university      VARCHAR(255),
            course          VARCHAR(64),
            branch          VARCHAR(255),
            year            INTEGER,
            semester        INTEGER,
            credits         FLOAT,
            max_marks       INTEGER,
            internal_marks  INTEGER,
            external_marks  INTEGER,
            lecture_hours   VARCHAR(32),
            total_hours     INTEGER,
            duration_hours  FLOAT,
            units           JSONB DEFAULT '[]',
            raw_metadata    JSONB DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("CREATE INDEX ix_syllabus_document_id ON syllabus (document_id)")
    op.execute("CREATE INDEX ix_syllabus_subject_code ON syllabus (subject_code)")
    op.execute("CREATE INDEX ix_syllabus_subject_name ON syllabus (subject_name)")
    # Trigram index for fast fuzzy matching on subject_name
    op.execute(
        "CREATE INDEX ix_syllabus_subject_name_trgm "
        "ON syllabus USING gin (subject_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_syllabus_semester ON syllabus (semester)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS syllabus CASCADE")
