"""
Database models — full schema for the RAG application.
"""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


# ─── Helper: SQLAlchemy Enum that uses Python enum .value (lowercase) ─────────
def _pg_enum(enum_cls, **kw):
    """PostgreSQL-native enum using the enum member .value strings."""
    return Enum(enum_cls, values_callable=lambda x: [e.value for e in x], **kw)


# ─── Enums ────────────────────────────────────────────────────────────────────


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    STAFF = "staff"
    STUDENT = "student"


class DocumentType(str, enum.Enum):
    NOTES = "notes"
    UNIVERSITY_EXAM = "university_exam"
    MID_TERM_EXAM = "mid_term_exam"  # upcoming feature — upload disabled
    SYLLABUS = "syllabus"


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class SessionType(str, enum.Enum):
    PERMANENT = "permanent"
    TEMPORARY = "temporary"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ─── Models ───────────────────────────────────────────────────────────────────


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(_pg_enum(UserRole), default=UserRole.STUDENT, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    documents = relationship("Document", back_populates="uploaded_by", lazy="selectin")
    conversations = relationship("Conversation", back_populates="user", lazy="selectin")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    uploaded_by_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    filename = Column(String(512), nullable=False)
    gcs_key = Column(String(1024), nullable=False, unique=True)
    document_type = Column(_pg_enum(DocumentType), nullable=False)
    status = Column(_pg_enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False, index=True)
    file_size_bytes = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    subject_name = Column(String(255), nullable=True)
    subject_code = Column(String(64), nullable=True)
    is_ocr_required = Column(Boolean, default=False)
    task_id = Column(String(255), nullable=True)  # Celery task ID
    error_message = Column(Text, nullable=True)
    doc_metadata = Column(JSON, default={})

    # Relationships
    uploaded_by = relationship("User", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="document", cascade="all, delete-orphan")
    syllabus_entries = relationship("Syllabus", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(TimestampMixin, Base):
    """
    Stores structured exam question chunks (university_exam / mid_term_exam).
    Each chunk represents one question extracted from the exam paper.
    """
    __tablename__ = "document_chunks"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)

    # Exam-specific fields populated by ExamProcessor
    part = Column(String(64), nullable=True)          # e.g. "Part A", "Part B"
    question_no = Column(String(32), nullable=True)   # e.g. "1", "2a"
    marks = Column(Integer, nullable=True)
    question_type = Column(String(64), nullable=True)  # e.g. "short_answer", "essay"

    subject_name = Column(String(255), nullable=True)
    subject_code = Column(String(64), nullable=True)
    document_type = Column(_pg_enum(DocumentType), nullable=False)
    priority = Column(Float, default=1.0)  # boost factor for retrieval
    token_count = Column(Integer, nullable=True)
    chunk_metadata = Column(JSON, default={})

    # pgvector embedding (3072-dim from gemini-embedding-001)
    embedding = Column(Vector(3072), nullable=True)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )


class Note(TimestampMixin, Base):
    """
    Stores lecture note chunks (document_type=notes).
    Each row is one chunk from a notes PDF, with its embedding for similarity search.
    """
    __tablename__ = "notes"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    subject = Column(String(255), nullable=True)
    semester = Column(String(64), nullable=True)

    # pgvector embedding (3072-dim from gemini-embedding-001)
    embedding = Column(Vector(3072), nullable=True)

    chunk_metadata = Column(JSON, default={})

    document = relationship("Document", back_populates="notes")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_note_chunk_index"),
    )


class Syllabus(TimestampMixin, Base):
    """
    One row per subject extracted from a syllabus PDF.
    units is a JSONB array: [{unit_no, unit_title, topics: [...], hours, raw_content}]
    Fuzzy subject name matching via pg_trgm similarity().
    """
    __tablename__ = "syllabus"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_code = Column(String(64), nullable=True, index=True)
    subject_name = Column(String(255), nullable=False, index=True)
    university = Column(String(255), nullable=True)
    course = Column(String(64), nullable=True)
    branch = Column(String(255), nullable=True)
    year = Column(Integer, nullable=True)
    semester = Column(Integer, nullable=True)
    credits = Column(Float, nullable=True)
    max_marks = Column(Integer, nullable=True)
    internal_marks = Column(Integer, nullable=True)
    external_marks = Column(Integer, nullable=True)
    lecture_hours = Column(String(32), nullable=True)
    total_hours = Column(Integer, nullable=True)
    duration_hours = Column(Float, nullable=True)
    units = Column(JSON, default=[])          # [{unit_no, unit_title, topics, hours, raw_content}]
    raw_metadata = Column(JSON, default={})

    document = relationship("Document", back_populates="syllabus_entries")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # null = anonymous
    session_type = Column(_pg_enum(SessionType), default=SessionType.PERMANENT, nullable=False)
    title = Column(String(512), nullable=True)
    summary = Column(Text, nullable=True)  # rolling conversation summary
    session_id = Column(String(255), nullable=True, index=True)  # for anonymous sessions
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # for temp sessions
    conv_metadata = Column(JSON, default={})

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at", lazy="selectin")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id = Column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(_pg_enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    retrieved_chunk_ids = Column(JSON, default=[])  # track which chunks were used
    model_used = Column(String(128), nullable=True)
    token_count = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
