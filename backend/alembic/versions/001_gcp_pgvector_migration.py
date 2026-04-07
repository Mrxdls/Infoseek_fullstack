"""Initial schema: GCP + pgvector — users, documents, chunks, notes, conversations, messages

Revision ID: 001_gcp_pgvector
Revises:
Create Date: 2026-04-04
"""

from alembic import op

revision = "001_gcp_pgvector"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("CREATE TYPE userrole AS ENUM ('admin', 'staff', 'student')")
    op.execute("CREATE TYPE documenttype AS ENUM ('notes', 'university_exam', 'mid_term_exam')")
    op.execute("CREATE TYPE documentstatus AS ENUM ('pending', 'processing', 'indexed', 'failed')")
    op.execute("CREATE TYPE sessiontype AS ENUM ('permanent', 'temporary')")
    op.execute("CREATE TYPE messagerole AS ENUM ('user', 'assistant', 'system')")

    op.execute("""
        CREATE TABLE users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           VARCHAR(255) NOT NULL UNIQUE,
            hashed_password VARCHAR(255) NOT NULL,
            full_name       VARCHAR(255),
            role            userrole NOT NULL DEFAULT 'student',
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
            last_login      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_users_email ON users (email)")

    op.execute("""
        CREATE TABLE refresh_tokens (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash  VARCHAR(255) NOT NULL UNIQUE,
            expires_at  TIMESTAMPTZ NOT NULL,
            revoked     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE documents (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            uploaded_by_id   UUID NOT NULL REFERENCES users(id),
            filename         VARCHAR(512) NOT NULL,
            gcs_key          VARCHAR(1024) NOT NULL UNIQUE,
            document_type    documenttype NOT NULL,
            status           documentstatus NOT NULL DEFAULT 'pending',
            file_size_bytes  INTEGER,
            page_count       INTEGER,
            subject_name     VARCHAR(255),
            subject_code     VARCHAR(64),
            is_ocr_required  BOOLEAN DEFAULT FALSE,
            task_id          VARCHAR(255),
            error_message    TEXT,
            doc_metadata     JSONB DEFAULT '{}',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_documents_status ON documents (status)")

    op.execute("""
        CREATE TABLE document_chunks (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id    UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index    INTEGER NOT NULL,
            chunk_text     TEXT NOT NULL,
            part           VARCHAR(64),
            question_no    VARCHAR(32),
            marks          INTEGER,
            question_type  VARCHAR(64),
            subject_name   VARCHAR(255),
            subject_code   VARCHAR(64),
            document_type  documenttype NOT NULL,
            priority       FLOAT DEFAULT 1.0,
            token_count    INTEGER,
            chunk_metadata JSONB DEFAULT '{}',
            embedding      vector(3072),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_document_chunk_index UNIQUE (document_id, chunk_index)
        )
    """)
    op.execute("CREATE INDEX ix_document_chunks_document_id ON document_chunks (document_id)")
    # NOTE: pgvector 0.6 limits both HNSW and IVFFlat to 2000 dims.
    # With 3072-dim embeddings we skip the ANN index for now — sequential scan
    # (ORDER BY embedding <=> :vec) is fine for development data volumes.
    # Upgrade to pgvector 0.7+ on Cloud SQL for production to add HNSW index.

    op.execute("""
        CREATE TABLE notes (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id    UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index    INTEGER NOT NULL,
            page_number    INTEGER,
            content        TEXT NOT NULL,
            subject        VARCHAR(255),
            semester       VARCHAR(64),
            chunk_metadata JSONB DEFAULT '{}',
            embedding      vector(3072),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_note_chunk_index UNIQUE (document_id, chunk_index)
        )
    """)
    op.execute("CREATE INDEX ix_notes_document_id ON notes (document_id)")
    # Same as document_chunks: skip vector index until pgvector >= 0.7

    op.execute("""
        CREATE TABLE conversations (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
            session_type  sessiontype NOT NULL DEFAULT 'permanent',
            title         VARCHAR(512),
            summary       TEXT,
            session_id    VARCHAR(255),
            is_active     BOOLEAN DEFAULT TRUE,
            expires_at    TIMESTAMPTZ,
            conv_metadata JSONB DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_conversations_session_id ON conversations (session_id)")

    op.execute("""
        CREATE TABLE messages (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id     UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role                messagerole NOT NULL,
            content             TEXT NOT NULL,
            retrieved_chunk_ids JSONB DEFAULT '[]',
            model_used          VARCHAR(128),
            token_count         INTEGER,
            latency_ms          INTEGER,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX ix_messages_conversation_id ON messages (conversation_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS messages CASCADE")
    op.execute("DROP TABLE IF EXISTS conversations CASCADE")
    op.execute("DROP TABLE IF EXISTS notes CASCADE")
    op.execute("DROP TABLE IF EXISTS document_chunks CASCADE")
    op.execute("DROP TABLE IF EXISTS documents CASCADE")
    op.execute("DROP TABLE IF EXISTS refresh_tokens CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
    op.execute("DROP TYPE IF EXISTS messagerole")
    op.execute("DROP TYPE IF EXISTS sessiontype")
    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP TYPE IF EXISTS documenttype")
    op.execute("DROP TYPE IF EXISTS userrole")
