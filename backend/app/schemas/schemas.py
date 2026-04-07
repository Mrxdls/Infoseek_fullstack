"""
Pydantic v2 schemas for all API endpoints.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.db.models.models import DocumentType, MessageRole, SessionType, UserRole


# ─── Auth ─────────────────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: Optional[str]
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Documents ────────────────────────────────────────────────────────────────


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    filename: str
    document_type: DocumentType
    status: str
    task_id: str
    message: str


class DocumentStatusResponse(BaseModel):
    document_id: UUID
    status: str
    filename: str
    document_type: DocumentType
    subject_name: Optional[str]
    subject_code: Optional[str]
    page_count: Optional[int]
    chunk_count: Optional[int]
    created_at: datetime
    error_message: Optional[str]

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: List[DocumentStatusResponse]
    total: int
    page: int
    page_size: int


# ─── Chat ─────────────────────────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    session_type: SessionType = SessionType.PERMANENT


class ConversationResponse(BaseModel):
    id: UUID
    title: Optional[str]
    session_type: SessionType
    summary: Optional[str]
    created_at: datetime
    message_count: Optional[int] = 0

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=4096)

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        # Basic sanitization — more thorough sanitization in the service layer
        return v.strip()


class CitedChunk(BaseModel):
    chunk_id: str
    source_type: str          # "exam" or "notes"
    subject_name: Optional[str]
    subject_code: Optional[str]
    excerpt: str
    relevance_score: float


class ChatResponse(BaseModel):
    message_id: UUID
    conversation_id: UUID
    answer: str
    intent: Optional[str] = None
    sources: List[CitedChunk]
    model_used: str
    latency_ms: int


class MessageResponse(BaseModel):
    id: UUID
    role: MessageRole
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationHistoryResponse(BaseModel):
    conversation: ConversationResponse
    messages: List[MessageResponse]


# ─── Admin ────────────────────────────────────────────────────────────────────


class UserUpdateRole(BaseModel):
    role: UserRole


class UserBlock(BaseModel):
    is_active: bool
    reason: Optional[str] = None
