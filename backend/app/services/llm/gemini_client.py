"""
Gemini client — single wrapper around google-genai SDK for Vertex AI.
All LLM and embedding calls across the codebase go through this module.
"""

import json
import os
import re
from typing import AsyncGenerator, List, Optional

import structlog
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings

logger = structlog.get_logger()

# Module-level client — initialised once
_client: Optional[genai.Client] = None


def get_gemini_client() -> genai.Client:
    global _client
    if _client is None:
        # Set credentials env var if configured
        if settings.GOOGLE_APPLICATION_CREDENTIALS:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS
        _client = genai.Client(
            vertexai=True,
            project=settings.GCP_PROJECT_ID,
            location=settings.GCP_LOCATION,
        )
    return _client


class GeminiClient:
    """
    Thin, opinionated wrapper around the google-genai Vertex AI SDK.

    Provides:
    - generate()        — sync text generation (Celery tasks)
    - agenerate()       — async text generation (FastAPI endpoints)
    - astream()         — async token streaming (SSE endpoint)
    - generate_json()   — sync JSON generation with auto-retry
    - embed_texts()     — batch embed up to EMBED_BATCH_SIZE per call
    - embed_query()     — single embedding
    """

    def __init__(self):
        self._c = get_gemini_client()
        self._large = settings.GEMINI_LARGE_MODEL
        self._small = settings.GEMINI_SMALL_MODEL
        self._embed_model = settings.EMBEDDING_MODEL
        self._batch = settings.EMBED_BATCH_SIZE

    # ── Text Generation ──────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """Synchronous generation — used inside Celery tasks. Auto-retries 3x."""
        model = model or self._small
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system,
        )
        contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        response = self._c.models.generate_content(
            model=model, contents=contents, config=config
        )
        return response.text or ""

    async def agenerate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """Async generation — used in FastAPI endpoints."""
        import asyncio
        return await asyncio.to_thread(
            self.generate, prompt, model, system, temperature, max_tokens
        )

    async def agenerate_with_history(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """Async generation with full conversation history."""
        import asyncio

        def _run():
            contents = [
                types.Content(
                    role=m["role"],
                    parts=[types.Part(text=m["content"])],
                )
                for m in messages
            ]
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                system_instruction=system,
            )
            response = self._c.models.generate_content(
                model=model or self._large,
                contents=contents,
                config=config,
            )
            return response.text or ""

        return await asyncio.to_thread(_run)

    async def astream(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        Async token streaming — yields text chunks for SSE.
        Wraps the sync SDK stream in a thread + async queue.
        """
        import asyncio
        import queue as _queue

        token_queue: _queue.Queue = _queue.Queue()
        sentinel = object()

        def _stream_in_thread():
            try:
                contents = [
                    types.Content(role=m["role"], parts=[types.Part(text=m["content"])])
                    for m in messages
                ]
                config = types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    system_instruction=system,
                )
                for chunk in self._c.models.generate_content_stream(
                    model=model or self._large,
                    contents=contents,
                    config=config,
                ):
                    token = chunk.text or ""
                    if token:
                        token_queue.put(token)
            except Exception as exc:
                token_queue.put(exc)
            finally:
                token_queue.put(sentinel)

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _stream_in_thread)

        while True:
            item = await asyncio.to_thread(token_queue.get)
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise item
            yield item

        await future

    def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        retries: int = 2,
    ) -> dict:
        """
        Generate and parse JSON. Strips markdown fences if present.
        Retries on parse failure up to `retries` times.
        """
        model = model or self._large
        last_err = None
        for attempt in range(retries + 1):
            try:
                raw = self.generate(
                    prompt=prompt,
                    model=model,
                    system=system,
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
                # Strip markdown code fences if present
                raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
                raw = re.sub(r"\s*```$", "", raw.strip(), flags=re.MULTILINE)
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                last_err = exc
                logger.warning("JSON parse failed, retrying", attempt=attempt, error=str(exc))
        logger.error("generate_json failed after retries", error=str(last_err))
        return {}

    async def agenerate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 8192,
    ) -> dict:
        import asyncio
        return await asyncio.to_thread(self.generate_json, prompt, model, system, max_tokens)

    # ── Embeddings ───────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Batch embed texts. Respects EMBED_BATCH_SIZE limit per API call.
        Returns list of 3072-dim vectors in the same order as input.
        """
        if not texts:
            return []

        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i : i + self._batch]
            response = self._c.models.embed_content(
                model=self._embed_model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=settings.EMBEDDING_DIMS,
                ),
            )
            all_embeddings.extend([e.values for e in response.embeddings])

        return all_embeddings

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query string (uses RETRIEVAL_QUERY task type)."""
        response = self._c.models.embed_content(
            model=self._embed_model,
            contents=[query],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=settings.EMBEDDING_DIMS,
            ),
        )
        return response.embeddings[0].values

    async def aembed_query(self, query: str) -> List[float]:
        import asyncio
        return await asyncio.to_thread(self.embed_query, query)
