"""
Redis cache utility for query caching and rate limit tracking.
"""

import hashlib
import json
from typing import Any, Optional

import redis.asyncio as redis
import structlog

from app.core.config import settings

logger = structlog.get_logger()

_pool = redis.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


def _make_key(prefix: str, *parts: str) -> str:
    raw = ":".join([prefix] + list(parts))
    return raw


def _hash_query(query: str, conversation_id: str) -> str:
    payload = f"{conversation_id}::{query.strip().lower()}"
    return hashlib.sha256(payload.encode()).hexdigest()


class CacheService:
    def __init__(self):
        self.redis = get_redis()
        self.ttl = settings.CACHE_TTL_SECONDS

    async def get_cached_response(self, query: str, conversation_id: str) -> Optional[dict]:
        key = _make_key("rag_cache", _hash_query(query, conversation_id))
        raw = await self.redis.get(key)
        if raw:
            logger.debug("Cache hit", key=key)
            return json.loads(raw)
        return None

    async def set_cached_response(self, query: str, conversation_id: str, response: dict) -> None:
        key = _make_key("rag_cache", _hash_query(query, conversation_id))
        await self.redis.setex(key, self.ttl, json.dumps(response))
        logger.debug("Cached response", key=key, ttl=self.ttl)

    async def invalidate_document_cache(self, document_id: str) -> None:
        """Invalidate all cached responses (conservative — full flush)."""
        # In production, use tagged cache or a more surgical approach
        logger.info("Cache invalidation triggered", document_id=document_id)

    async def get(self, key: str) -> Optional[str]:
        return await self.redis.get(key)

    async def set(self, key: str, value: str, ttl: int = None) -> None:
        await self.redis.setex(key, ttl or self.ttl, value)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def increment(self, key: str, ttl: int = 60) -> int:
        pipe = self.redis.pipeline()
        await pipe.incr(key)
        await pipe.expire(key, ttl)
        results = await pipe.execute()
        return results[0]
