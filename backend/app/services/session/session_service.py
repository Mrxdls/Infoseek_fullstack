"""
Session and conversation management.
Handles short-term memory, conversation summarization, and anonymous sessions.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.models import Conversation, Message, MessageRole, SessionType, User
from app.services.llm.gemini_client import GeminiClient

logger = structlog.get_logger()

_gemini = GeminiClient()

SUMMARIZE_PROMPT = """Summarize the following conversation concisely.
Preserve key topics, questions asked, and important answers given.
Keep the summary under 300 words.

Conversation:
{conversation}

Summary:"""


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_conversation(
        self,
        user: Optional[User],
        title: Optional[str] = None,
        session_type: SessionType = SessionType.PERMANENT,
        session_id: Optional[str] = None,
    ) -> Conversation:
        expires_at = None
        if session_type == SessionType.TEMPORARY:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.ANON_SESSION_TTL_HOURS)

        conv = Conversation(
            user_id=user.id if user else None,
            title=title or "New Conversation",
            session_type=session_type,
            session_id=session_id,
            expires_at=expires_at,
        )
        self.db.add(conv)
        await self.db.flush()
        return conv

    async def get_conversation(
        self,
        conversation_id: UUID,
        user: Optional[User] = None,
    ) -> Optional[Conversation]:
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()

        if not conv:
            return None

        # Check ownership
        if user and conv.user_id and conv.user_id != user.id:
            return None  # forbidden

        # Check expiry for temp sessions
        if conv.expires_at and conv.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            conv.is_active = False
            return None

        return conv

    async def list_conversations(self, user: User, page: int = 1, page_size: int = 20) -> List[Conversation]:
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.is_active == True)
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return result.scalars().all()

    async def add_message(
        self,
        conversation_id: UUID,
        role: MessageRole,
        content: str,
        retrieved_chunk_ids: Optional[List[str]] = None,
        model_used: Optional[str] = None,
        token_count: Optional[int] = None,
        latency_ms: Optional[int] = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            retrieved_chunk_ids=retrieved_chunk_ids or [],
            model_used=model_used,
            token_count=token_count,
            latency_ms=latency_ms,
        )
        self.db.add(msg)
        await self.db.flush()
        await self.db.commit()   # commit immediately — never lose messages
        return msg

    async def get_recent_messages(
        self,
        conversation_id: UUID,
        limit: int = None,
    ) -> List[dict]:
        """Returns recent messages as plain dicts for LLM context."""
        limit = limit or settings.SHORT_TERM_MEMORY_MESSAGES
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = result.scalars().all()
        # Return in chronological order
        return [
            {"role": m.role.value, "content": m.content}
            for m in reversed(messages)
        ]

    async def get_or_update_summary(self, conversation: Conversation) -> Optional[str]:
        """
        Returns existing summary or triggers summarization if enough messages
        have accumulated since the last summary.
        """
        # Count total messages
        count_result = await self.db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
        )
        total = count_result.scalar()

        # Trigger summarization if threshold exceeded and no recent summary
        if total > 0 and total % settings.SUMMARY_TRIGGER_MESSAGES == 0:
            await self._update_summary(conversation)

        return conversation.summary

    async def _update_summary(self, conversation: Conversation) -> None:
        """Summarize conversation using small LLM model."""
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
            .limit(settings.SUMMARY_TRIGGER_MESSAGES)
        )
        messages = result.scalars().all()

        if not messages:
            return

        convo_text = "\n".join(
            f"{m.role.value.upper()}: {m.content}" for m in messages
        )
        prompt = SUMMARIZE_PROMPT.format(conversation=convo_text)
        summary = await _gemini.agenerate(
            prompt=prompt,
            model=_gemini._small,
            max_tokens=400,
            temperature=0.0,
        )
        conversation.summary = summary.strip()
        logger.info("Conversation summary updated", conversation_id=str(conversation.id))

    async def expire_stale_sessions(self) -> int:
        """Mark expired temporary sessions as inactive. Called by Celery beat."""
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.session_type == SessionType.TEMPORARY,
                Conversation.is_active == True,
                Conversation.expires_at < datetime.now(timezone.utc),
            )
        )
        stale = result.scalars().all()
        for conv in stale:
            conv.is_active = False

        logger.info("Expired stale sessions", count=len(stale))
        return len(stale)
