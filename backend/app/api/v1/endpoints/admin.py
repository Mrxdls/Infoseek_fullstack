"""
Admin endpoints — user management, chat monitoring, system stats.
Accessible only to ADMIN role.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import limiter, AUTH_RATE
from app.db.models.models import Conversation, Document, Message, User, UserRole
from app.db.session import get_db
from app.schemas.schemas import (
    ConversationHistoryResponse,
    ConversationResponse,
    MessageResponse,
    UserBlock,
    UserResponse,
    UserUpdateRole,
)
from app.services.auth.auth_service import get_current_admin, get_current_active_admin

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/users", response_model=List[UserResponse])
@limiter.limit(AUTH_RATE)
async def list_users(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_admin),
):
    result = await db.execute(
        select(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


@router.patch("/users/{user_id}/role", response_model=UserResponse)
@limiter.limit(AUTH_RATE)
async def update_user_role(
    request: Request,
    user_id: UUID,
    body: UserUpdateRole,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Super admin only — cannot self-demote."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = body.role
    return user


@router.patch("/users/{user_id}/block", response_model=UserResponse)
@limiter.limit(AUTH_RATE)
async def block_user(
    request: Request,
    user_id: UUID,
    body: UserBlock,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_active_admin),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = body.is_active
    return user


@router.get("/users/{user_id}/conversations", response_model=List[ConversationResponse])
@limiter.limit(AUTH_RATE)
async def get_user_conversations(
    request: Request,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_admin),
):
    """View conversations of any student — for performance analysis."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()
    return [
        ConversationResponse(
            id=c.id,
            title=c.title,
            session_type=c.session_type,
            summary=c.summary,
            created_at=c.created_at,
            message_count=len(c.messages),
        )
        for c in convs
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationHistoryResponse)
@limiter.limit(AUTH_RATE)
async def admin_view_conversation(
    request: Request,
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_admin),
):
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = [
        MessageResponse(id=m.id, role=m.role, content=m.content, created_at=m.created_at)
        for m in conv.messages
    ]
    return ConversationHistoryResponse(
        conversation=ConversationResponse(
            id=conv.id,
            title=conv.title,
            session_type=conv.session_type,
            summary=conv.summary,
            created_at=conv.created_at,
            message_count=len(messages),
        ),
        messages=messages,
    )


@router.get("/stats")
@limiter.limit(AUTH_RATE)
async def system_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_admin),
):
    from sqlalchemy import func

    user_count = (await db.execute(select(func.count(User.id)))).scalar()
    doc_count = (await db.execute(select(func.count(Document.id)))).scalar()
    conv_count = (await db.execute(select(func.count(Conversation.id)))).scalar()
    msg_count = (await db.execute(select(func.count(Message.id)))).scalar()

    return {
        "total_users": user_count,
        "total_documents": doc_count,
        "total_conversations": conv_count,
        "total_messages": msg_count,
    }
