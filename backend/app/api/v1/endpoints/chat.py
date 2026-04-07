"""
Chat endpoints — conversation management and RAG query execution.
Supports both standard JSON responses and SSE streaming.
"""

import json
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import limiter, AUTH_RATE
from app.db.models.models import MessageRole, SessionType, User
from app.db.session import get_db
from app.schemas.schemas import (
    ChatRequest,
    ChatResponse,
    CitedChunk,
    ConversationCreate,
    ConversationHistoryResponse,
    ConversationResponse,
    MessageResponse,
)
from app.services.auth.auth_service import get_current_user
from app.services.rag.pipeline import RAGPipeline
from app.services.session.session_service import SessionService
from app.utils.cache import CacheService

logger = structlog.get_logger()
router = APIRouter(prefix="/chat", tags=["Chat"])


# ─── Conversations ────────────────────────────────────────────────────────────


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
@limiter.limit(AUTH_RATE)
async def create_conversation(
    request: Request,
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SessionService(db)
    conv = await svc.create_conversation(
        user=current_user,
        title=body.title,
        session_type=body.session_type,
    )
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        session_type=conv.session_type,
        summary=conv.summary,
        created_at=conv.created_at,
        message_count=0,
    )


@router.get("/conversations", response_model=List[ConversationResponse])
@limiter.limit(AUTH_RATE)
async def list_conversations(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SessionService(db)
    convs = await svc.list_conversations(current_user, page, page_size)
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
async def get_conversation_history(
    request: Request,
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = SessionService(db)
    conv = await svc.get_conversation(conversation_id, current_user)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
        )
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


# ─── Query (RAG) ─────────────────────────────────────────────────────────────


@router.post("/query", response_model=ChatResponse)
@limiter.limit(AUTH_RATE)
async def query(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Main RAG query endpoint.
    Intent is classified, retrieval routes to exam chunks / notes / both.
    """
    svc = SessionService(db)
    cache = CacheService()

    conv = await svc.get_conversation(body.conversation_id, current_user)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Cache check
    cached = await cache.get_cached_response(body.message, str(body.conversation_id))
    if cached:
        return ChatResponse(**cached)

    recent_messages = await svc.get_recent_messages(body.conversation_id)
    summary = await svc.get_or_update_summary(conv)

    await svc.add_message(
        conversation_id=body.conversation_id,
        role=MessageRole.USER,
        content=body.message,
    )

    pipeline = RAGPipeline()
    result = await pipeline.run(
        query=body.message,
        db=db,
        recent_messages=recent_messages,
        conversation_summary=summary,
    )

    chunk_ids = [s.chunk_id for s in result.sources]
    assistant_msg = await svc.add_message(
        conversation_id=body.conversation_id,
        role=MessageRole.ASSISTANT,
        content=result.answer,
        retrieved_chunk_ids=chunk_ids,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
    )

    sources = [
        CitedChunk(
            chunk_id=s.chunk_id,
            source_type=s.source_type,
            subject_name=s.subject_name,
            subject_code=s.subject_code,
            excerpt=s.chunk_text[:300] + ("..." if len(s.chunk_text) > 300 else ""),
            relevance_score=round(s.score, 4),
        )
        for s in result.sources
    ]

    response = ChatResponse(
        message_id=assistant_msg.id,
        conversation_id=body.conversation_id,
        answer=result.answer,
        intent=result.intent,
        sources=sources,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
    )

    if not result.was_refused:
        await cache.set_cached_response(
            body.message,
            str(body.conversation_id),
            response.model_dump(mode="json"),
        )

    return response


@router.post("/query/stream")
@limiter.limit(AUTH_RATE)
async def query_stream(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Streaming RAG query using Server-Sent Events.
    Yields tokens from Gemini as they arrive.
    """
    svc = SessionService(db)
    conv = await svc.get_conversation(body.conversation_id, current_user)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    recent_messages = await svc.get_recent_messages(body.conversation_id)
    summary = await svc.get_or_update_summary(conv)

    await svc.add_message(
        conversation_id=body.conversation_id,
        role=MessageRole.USER,
        content=body.message,
    )

    pipeline = RAGPipeline()

    async def event_generator():
        full_answer = []
        try:
            async for token in pipeline.stream(
                query=body.message,
                db=db,
                recent_messages=recent_messages,
                conversation_summary=summary,
            ):
                full_answer.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"

            final = "".join(full_answer)
            await svc.add_message(
                conversation_id=body.conversation_id,
                role=MessageRole.ASSISTANT,
                content=final,
                model_used="gemini-2.5-pro",
            )
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error("Streaming error", error=str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
