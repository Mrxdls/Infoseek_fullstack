"""
pgvector store — replaces Qdrant.
Handles embedding, upsert, and similarity search for exam chunks and notes.
"""

import uuid
from typing import List, Optional

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.ingestion.chunker import Chunk
from app.services.llm.gemini_client import GeminiClient

logger = structlog.get_logger()


class VectorStoreService:
    """
    pgvector-backed vector store.
    Exam questions → document_chunks table.
    Lecture notes   → notes table.
    """

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self._gemini = gemini_client or GeminiClient()

    # ── Embedding helpers ────────────────────────────────────────────────────

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self._gemini.embed_texts(texts)

    def _embed_query(self, query: str) -> List[float]:
        return self._gemini.embed_query(query)

    async def _aembed_query(self, query: str) -> List[float]:
        return await self._gemini.aembed_query(query)

    # ── Exam chunk upsert ────────────────────────────────────────────────────

    async def upsert_exam_chunks(
        self,
        session: AsyncSession,
        document_id: str,
        chunks: List[Chunk],
    ) -> int:
        """
        Embed and insert exam question chunks into document_chunks.
        Returns the number of rows inserted.
        """
        if not chunks:
            return 0

        texts = [c.chunk_text for c in chunks]
        embeddings = self._embed_batch(texts)

        rows = []
        for chunk, embedding in zip(chunks, embeddings):
            rows.append({
                "id": str(uuid.uuid4()),
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "chunk_text": chunk.chunk_text,
                "part": chunk.part,
                "question_no": chunk.question_no,
                "marks": chunk.marks,
                "question_type": chunk.question_type,
                "subject_name": chunk.subject_name,
                "subject_code": chunk.subject_code,
                "document_type": chunk.document_type.value,
                "priority": chunk.priority,
                "chunk_metadata": chunk.metadata,
                "embedding": str(embedding),  # pgvector accepts '[1.0, 2.0, ...]' string
            })

        await session.execute(
            text("""
                INSERT INTO document_chunks
                    (id, document_id, chunk_index, chunk_text,
                     part, question_no, marks, question_type,
                     subject_name, subject_code, document_type, priority,
                     chunk_metadata, embedding)
                VALUES
                    (:id, :document_id, :chunk_index, :chunk_text,
                     :part, :question_no, :marks, :question_type,
                     :subject_name, :subject_code, CAST(:document_type AS documenttype), :priority,
                     CAST(:chunk_metadata AS jsonb), CAST(:embedding AS vector))
                ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                    chunk_text  = EXCLUDED.chunk_text,
                    embedding   = EXCLUDED.embedding,
                    updated_at  = NOW()
            """),
            rows,
        )

        logger.info("Exam chunks upserted", document_id=document_id, count=len(rows))
        return len(rows)

    # ── Notes upsert ─────────────────────────────────────────────────────────

    async def upsert_notes(
        self,
        session: AsyncSession,
        document_id: str,
        note_chunks,  # List[NoteChunk] from notes_processor
    ) -> int:
        """
        Embed and insert lecture note chunks into notes table.
        Returns the number of rows inserted.
        """
        if not note_chunks:
            return 0

        texts = [n.content for n in note_chunks]
        embeddings = self._embed_batch(texts)

        rows = []
        for note, embedding in zip(note_chunks, embeddings):
            rows.append({
                "id": str(uuid.uuid4()),
                "document_id": document_id,
                "chunk_index": note.chunk_index,
                "page_number": note.page_number,
                "content": note.content,
                "subject": note.subject,
                "semester": note.semester,
                "chunk_metadata": note.metadata,
                "embedding": str(embedding),
            })

        await session.execute(
            text("""
                INSERT INTO notes
                    (id, document_id, chunk_index, page_number, content,
                     subject, semester, chunk_metadata, embedding)
                VALUES
                    (:id, :document_id, :chunk_index, :page_number, :content,
                     :subject, :semester, CAST(:chunk_metadata AS jsonb),
                     CAST(:embedding AS vector))
                ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                    content     = EXCLUDED.content,
                    embedding   = EXCLUDED.embedding,
                    updated_at  = NOW()
            """),
            rows,
        )

        logger.info("Note chunks upserted", document_id=document_id, count=len(rows))
        return len(rows)

    # ── Exam chunk search ────────────────────────────────────────────────────

    async def search_exam_chunks(
        self,
        session: AsyncSession,
        query: str,
        top_k: int = None,
        score_threshold: float = None,
        subject_code: Optional[str] = None,
    ) -> List[dict]:
        """
        Cosine similarity search over document_chunks (exam questions).
        Returns top_k results above score_threshold.
        """
        top_k = top_k or settings.TOP_K_RETRIEVAL
        score_threshold = score_threshold or settings.SIMILARITY_THRESHOLD

        query_vec = await self._aembed_query(query)
        vec_str = str(query_vec)

        subject_filter = ""
        params: dict = {
            "vec": vec_str,
            "threshold": 1 - score_threshold,  # cosine distance = 1 - similarity
            "top_k": top_k,
        }
        if subject_code:
            subject_filter = "AND subject_code = :subject_code"
            params["subject_code"] = subject_code

        rows = await session.execute(
            text(f"""
                SELECT
                    id::text,
                    chunk_text,
                    part,
                    question_no,
                    marks,
                    question_type,
                    subject_name,
                    subject_code,
                    document_type::text,
                    priority,
                    chunk_metadata,
                    1 - (embedding <=> CAST(:vec AS vector)) AS score
                FROM document_chunks
                WHERE embedding IS NOT NULL
                  AND (embedding <=> CAST(:vec AS vector)) < :threshold
                  {subject_filter}
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :top_k
            """),
            params,
        )

        results = []
        for row in rows.mappings():
            results.append({
                "id": row["id"],
                "chunk_text": row["chunk_text"],
                "part": row["part"],
                "question_no": row["question_no"],
                "marks": row["marks"],
                "question_type": row["question_type"],
                "subject_name": row["subject_name"],
                "subject_code": row["subject_code"],
                "document_type": row["document_type"],
                "score": float(row["score"]),
                "source_type": "exam",
            })

        return self._mmr_rerank(results, query_vec)

    # ── Notes search ─────────────────────────────────────────────────────────

    async def search_notes(
        self,
        session: AsyncSession,
        query: str,
        top_k: int = None,
        score_threshold: float = None,
        subject: Optional[str] = None,
    ) -> List[dict]:
        """
        Cosine similarity search over notes table (lecture notes).
        """
        top_k = top_k or settings.TOP_K_RETRIEVAL
        score_threshold = score_threshold or settings.SIMILARITY_THRESHOLD

        query_vec = await self._aembed_query(query)
        vec_str = str(query_vec)

        subject_filter = ""
        params: dict = {
            "vec": vec_str,
            "threshold": 1 - score_threshold,
            "top_k": top_k,
        }
        if subject:
            subject_filter = "AND subject ILIKE :subject"
            params["subject"] = f"%{subject}%"

        rows = await session.execute(
            text(f"""
                SELECT
                    id::text,
                    content,
                    page_number,
                    subject,
                    semester,
                    chunk_metadata,
                    1 - (embedding <=> CAST(:vec AS vector)) AS score
                FROM notes
                WHERE embedding IS NOT NULL
                  AND (embedding <=> CAST(:vec AS vector)) < :threshold
                  {subject_filter}
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :top_k
            """),
            params,
        )

        results = []
        for row in rows.mappings():
            results.append({
                "id": row["id"],
                "chunk_text": row["content"],
                "page_number": row["page_number"],
                "subject": row["subject"],
                "semester": row["semester"],
                "score": float(row["score"]),
                "source_type": "notes",
            })

        return results

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_by_document_id(self, session: AsyncSession, document_id: str) -> None:
        await session.execute(
            text("DELETE FROM document_chunks WHERE document_id = CAST(:doc_id AS uuid)"),
            {"doc_id": document_id},
        )
        await session.execute(
            text("DELETE FROM notes WHERE document_id = CAST(:doc_id AS uuid)"),
            {"doc_id": document_id},
        )
        logger.info("Vectors deleted", document_id=document_id)

    # ── MMR re-ranking ────────────────────────────────────────────────────────

    def _mmr_rerank(
        self,
        results: List[dict],
        query_vec: List[float],
        top_k: int = None,
        lambda_mult: float = None,
    ) -> List[dict]:
        """
        Maximal Marginal Relevance: balance relevance vs diversity.
        Works on text-level similarity since we don't store vectors in results.
        """
        top_k = top_k or settings.TOP_K_RETRIEVAL
        lambda_mult = lambda_mult or settings.MMR_LAMBDA

        if len(results) <= 1:
            return results

        # Apply priority boost
        for r in results:
            pass  # score already computed; priority not in notes search

        # Simple text deduplication (MMR approximation without stored vectors)
        seen_texts: List[str] = []
        selected: List[dict] = []

        # Sort by score descending first
        results.sort(key=lambda x: x["score"], reverse=True)

        for r in results:
            text = r["chunk_text"]
            words = set(text.lower().split())
            is_dup = any(
                len(words & set(s.lower().split())) / max(len(words), 1) > 0.8
                for s in seen_texts
            )
            if not is_dup:
                selected.append(r)
                seen_texts.append(text)

            if len(selected) >= top_k:
                break

        return selected
