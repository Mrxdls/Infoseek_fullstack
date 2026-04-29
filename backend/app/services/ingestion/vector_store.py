"""
pgvector store — LangChain-compatible retriever with custom search optimization.
Handles embedding, upsert, and similarity search for exam chunks and notes.

Architecture:
- Embedding: Gemini embeddings (wrapped for LangChain)
- Upsert: SQLAlchemy ORM (with raw SQL reference)
- Search: Custom async SQL with vector operators (cosine similarity <=>)
- LangChain: Retriever interface for chain compatibility
"""

import uuid
from typing import List, Optional

import structlog
from sqlalchemy import text, select, and_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.db.models.models import DocumentChunk, Note
from app.services.ingestion.chunker import Chunk
from app.services.llm.gemini_client import GeminiClient

logger = structlog.get_logger()


# ── LangChain Embedding Wrapper ──────────────────────────────────────────────

class GeminiEmbeddings:
    """
    LangChain-compatible embedding function wrapping Gemini embeddings.
    Synchronous interface for LangChain compatibility.
    """

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self._gemini = gemini_client or GeminiClient()

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query (sync wrapper)."""
        return self._gemini.embed_query(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents (sync wrapper)."""
        return self._gemini.embed_texts(texts)

    def __call__(self, text: str) -> List[float]:
        """Allow direct calling for LangChain compatibility."""
        return self.embed_query(text)


# ── LangChain Retriever Interface ────────────────────────────────────────────

from langchain.schema import BaseRetriever, Document

class VectorStoreRetriever(BaseRetriever):
    """
    LangChain Retriever interface for VectorStoreService.
    Allows VectorStoreService to be used with LangChain chains.
    """

    vector_store: "VectorStoreService"
    session: AsyncSession
    search_type: str = "exam"  # "exam", "notes", or "hybrid"
    search_kwargs: dict = {}

    class Config:
        arbitrary_types_allowed = True

    async def _get_relevant_documents(self, query: str) -> List[Document]:
        """Retrieve relevant documents (async)."""
        if self.search_type == "exam":
            results = await self.vector_store.search_exam_chunks(
                session=self.session,
                query=query,
                **self.search_kwargs,
            )
        elif self.search_type == "notes":
            results = await self.vector_store.search_notes(
                session=self.session,
                query=query,
                **self.search_kwargs,
            )
        else:  # hybrid
            exam_results = await self.vector_store.search_exam_chunks(
                session=self.session,
                query=query,
                **self.search_kwargs,
            )
            notes_results = await self.vector_store.search_notes(
                session=self.session,
                query=query,
                **self.search_kwargs,
            )
            results = sorted(
                exam_results + notes_results,
                key=lambda x: x["score"],
                reverse=True,
            )[:self.search_kwargs.get("top_k", 8)]

        # Convert to LangChain Document format
        documents = []
        for result in results:
            doc = Document(
                page_content=result["chunk_text"],
                metadata={
                    "id": result["id"],
                    "source_type": result.get("source_type", "unknown"),
                    "score": result.get("score", 0.0),
                    "subject_name": result.get("subject_name"),
                    "subject_code": result.get("subject_code"),
                    **(result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {}),
                },
            )
            documents.append(doc)

        return documents


class VectorStoreService:
    """
    pgvector-backed vector store with LangChain Retriever interface.
    Exam questions → document_chunks table.
    Lecture notes   → notes table.

    Can be used:
    1. Directly: vs.search_exam_chunks(...) - returns custom dicts
    2. Via LangChain: vs.as_retriever() - returns LangChain Document objects
    """

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self._gemini = gemini_client or GeminiClient()
        self._embeddings = GeminiEmbeddings(self._gemini)

    # ── LangChain Retriever Interface ────────────────────────────────────────

    def as_retriever(
        self,
        session: AsyncSession,
        search_type: str = "hybrid",
        search_kwargs: Optional[dict] = None,
    ) -> VectorStoreRetriever:
        """
        Return a LangChain Retriever for use with chains.
        
        Args:
            session: AsyncSession for DB queries
            search_type: "exam", "notes", or "hybrid"
            search_kwargs: Additional search parameters (top_k, score_threshold, etc.)
        
        Returns:
            VectorStoreRetriever compatible with LangChain chains
        """
        return VectorStoreRetriever(
            vector_store=self,
            session=session,
            search_type=search_type,
            search_kwargs=search_kwargs or {},
        )

    # ── Embedding helpers ────────────────────────────────────────────────────

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embed texts using Gemini."""
        return self._embeddings.embed_documents(texts)

    def _embed_query(self, query: str) -> List[float]:
        """Synchronous query embedding."""
        return self._embeddings.embed_query(query)

    async def _aembed_query(self, query: str) -> List[float]:
        """Async query embedding."""
        return await self._gemini.aembed_query(query)

    # ── Exam chunk upsert ────────────────────────────────────────────────────

    async def upsert_exam_chunks(
        self,
        session: AsyncSession,
        document_id: str,
        chunks: List[Chunk],
    ) -> int:
        """
        Embed and upsert exam question chunks into document_chunks table using ORM.
        Returns the number of rows inserted/updated.
        
        Uses SQLAlchemy ON CONFLICT (upsert) for efficient batch operations.
        """
        if not chunks:
            return 0

        texts = [c.chunk_text for c in chunks]
        embeddings = self._embed_batch(texts)

        # Build ORM-compatible data
        rows = []
        for chunk, embedding in zip(chunks, embeddings):
            rows.append({
                "id": uuid.uuid4(),
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
                "embedding": embedding,
            })

        # ORM Upsert: INSERT ... ON CONFLICT DO UPDATE
        stmt = insert(DocumentChunk).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["document_id", "chunk_index"],
            set={
                DocumentChunk.chunk_text: stmt.excluded.chunk_text,
                DocumentChunk.embedding: stmt.excluded.embedding,
                DocumentChunk.updated_at: func.now(),
            }
        )

        await session.execute(stmt)
        await session.commit()

        logger.info("Exam chunks upserted (ORM)", document_id=document_id, count=len(rows))
        return len(rows)

        # ─── Raw SQL Reference (commented out) ──────────────────────────────
        # """
        # await session.execute(
        #     text(\"\"\"
        #         INSERT INTO document_chunks
        #             (id, document_id, chunk_index, chunk_text,
        #              part, question_no, marks, question_type,
        #              subject_name, subject_code, document_type, priority,
        #              chunk_metadata, embedding)
        #         VALUES
        #             (:id, :document_id, :chunk_index, :chunk_text,
        #              :part, :question_no, :marks, :question_type,
        #              :subject_name, :subject_code, CAST(:document_type AS documenttype), :priority,
        #              CAST(:chunk_metadata AS jsonb), CAST(:embedding AS vector))
        #         ON CONFLICT (document_id, chunk_index) DO UPDATE SET
        #             chunk_text  = EXCLUDED.chunk_text,
        #             embedding   = EXCLUDED.embedding,
        #             updated_at  = NOW()
        #     \"\"\"),
        #     rows,
        # )
        # \"\"\"

    # ── Notes upsert ─────────────────────────────────────────────────────────

    async def upsert_notes(
        self,
        session: AsyncSession,
        document_id: str,
        note_chunks,  # List[NoteChunk] from notes_processor
    ) -> int:
        """
        Embed and upsert lecture note chunks into notes table using ORM.
        Returns the number of rows inserted/updated.
        
        Uses SQLAlchemy ON CONFLICT (upsert) for efficient batch operations.
        """
        if not note_chunks:
            return 0

        texts = [n.content for n in note_chunks]
        embeddings = self._embed_batch(texts)

        # Build ORM-compatible data
        rows = []
        for note, embedding in zip(note_chunks, embeddings):
            rows.append({
                "id": uuid.uuid4(),
                "document_id": document_id,
                "chunk_index": note.chunk_index,
                "page_number": note.page_number,
                "content": note.content,
                "subject": note.subject,
                "semester": note.semester,
                "chunk_metadata": note.metadata,
                "embedding": embedding,
            })

        # ORM Upsert: INSERT ... ON CONFLICT DO UPDATE
        stmt = insert(Note).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["document_id", "chunk_index"],
            set={
                Note.content: stmt.excluded.content,
                Note.embedding: stmt.excluded.embedding,
                Note.updated_at: func.now(),
            }
        )

        await session.execute(stmt)
        await session.commit()

        logger.info("Note chunks upserted (ORM)", document_id=document_id, count=len(rows))
        return len(rows)

        # ─── Raw SQL Reference (commented out) ──────────────────────────────
        # """
        # await session.execute(
        #     text(\"\"\"
        #         INSERT INTO notes
        #             (id, document_id, chunk_index, page_number, content,
        #              subject, semester, chunk_metadata, embedding)
        #         VALUES
        #             (:id, :document_id, :chunk_index, :page_number, :content,
        #              :subject, :semester, CAST(:chunk_metadata AS jsonb),
        #              CAST(:embedding AS vector))
        #         ON CONFLICT (document_id, chunk_index) DO UPDATE SET
        #             content     = EXCLUDED.content,
        #             embedding   = EXCLUDED.embedding,
        #             updated_at  = NOW()
        #     \"\"\"),
        #     rows,
        # )
        # \"\"\"

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
        Returns top_k results above score_threshold with MMR reranking.
        
        Note: Uses raw SQL because SQLAlchemy ORM has limited support for pgvector
        similarity operators (<=> for cosine distance). Consider ORM alternative
        if full type safety becomes important (see commented reference below).
        
        Compatible with LangChain via .as_retriever(search_type="exam")
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

        # ─── Raw SQL: Vector similarity search using pgvector ─────────────────
        # The <=> operator computes cosine distance between embedding vectors
        # We convert it to similarity score: similarity = 1 - distance
        sql_query = f"""
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
        """

        rows = await session.execute(text(sql_query), params)

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

        # ─── ORM Alternative Reference (for future migration) ────────────────────
        # """
        # SQLAlchemy with pgvector support (requires pgvector-python):
        #
        # from sqlalchemy import cast, desc
        # from pgvector.sqlalchemy import Vector
        #
        # stmt = select(DocumentChunk).where(
        #     and_(
        #         DocumentChunk.embedding.isnot(None),
        #         DocumentChunk.embedding.op("<=>", return_type=Float)(
        #             cast(vec_str, Vector(3072))
        #         ) < (1 - score_threshold)
        #     )
        # )
        # if subject_code:
        #     stmt = stmt.where(DocumentChunk.subject_code == subject_code)
        # 
        # stmt = stmt.order_by(
        #     DocumentChunk.embedding.op("<=>")(cast(vec_str, Vector(3072)))
        # ).limit(top_k)
        #
        # rows = await session.execute(stmt)
        # chunks = rows.scalars().all()
        # \"\"\"

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
        Returns top_k results with optional subject filtering.
        
        Note: Uses raw SQL for vector similarity (same reason as search_exam_chunks).
        
        Compatible with LangChain via .as_retriever(search_type="notes")
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

        # ─── Raw SQL: Vector similarity search using pgvector ─────────────────
        sql_query = f"""
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
        """

        rows = await session.execute(text(sql_query), params)

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

        # ─── Raw SQL Reference (for comparison) ─────────────────────────────────
        # """
        # Same vector similarity approach as search_exam_chunks.
        # ORM migration would require custom operators as shown above.
        # \"\"\"

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_by_document_id(self, session: AsyncSession, document_id: str) -> None:
        """
        Delete all chunks associated with a document using ORM.
        Cascades to both document_chunks and notes tables.
        """
        # ORM Delete: Delete exam chunks
        from uuid import UUID
        
        doc_uuid = UUID(document_id) if isinstance(document_id, str) else document_id
        
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == doc_uuid)
        await session.execute(stmt)
        
        # ORM Delete: Delete notes
        stmt = delete(Note).where(Note.document_id == doc_uuid)
        await session.execute(stmt)
        
        await session.commit()
        
        logger.info("Vectors deleted (ORM)", document_id=document_id)

        # ─── Raw SQL Reference (commented out) ──────────────────────────────
        # """
        # await session.execute(
        #     text("DELETE FROM document_chunks WHERE document_id = CAST(:doc_id AS uuid)"),
        #     {"doc_id": document_id},
        # )
        # await session.execute(
        #     text("DELETE FROM notes WHERE document_id = CAST(:doc_id AS uuid)"),
        #     {"doc_id": document_id},
        # )
        # \"\"\"

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


# ── LangChain Usage Examples ─────────────────────────────────────────────────

"""
EXAMPLE 1: Direct search (backward compatible - existing code works unchanged)
    
    vs = VectorStoreService()
    results = await vs.search_exam_chunks(session, "what is TCP?", top_k=5)
    # Returns: List[dict] with score, chunk_text, metadata, etc.

EXAMPLE 2: LangChain Retriever for RAG chains

    vs = VectorStoreService()
    
    # Create LangChain retriever
    retriever = vs.as_retriever(
        session=db_session,
        search_type="hybrid",  # or "exam" or "notes"
        search_kwargs={"top_k": 8, "score_threshold": 0.65}
    )
    
    # Use with LangChain RetrievalQA
    from langchain.chains import RetrievalQA
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    qa_chain = RetrievalQA.from_chain_type(
        llm=ChatGoogleGenerativeAI(model="gemini-pro"),
        chain_type="stuff",
        retriever=retriever,
    )
    
    answer = await qa_chain.arun("Explain TCP protocol")

EXAMPLE 3: LangChain RAG with custom prompt

    from langchain.prompts import ChatPromptTemplate
    from langchain.schema.runnable import RunnablePassthrough
    from langchain_core.output_parsers import StrOutputParser
    
    retriever = vs.as_retriever(session=db_session, search_type="notes")
    
    template = '''Answer based on context:
    Context: {context}
    Question: {question}'''
    
    prompt = ChatPromptTemplate.from_template(template)
    
    chain = (
        {"context": retriever, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    
    answer = await chain.ainvoke("What is a vector database?")

EXAMPLE 4: Multi-retriever hybrid search

    exam_retriever = vs.as_retriever(session, search_type="exam", search_kwargs={"top_k": 5})
    notes_retriever = vs.as_retriever(session, search_type="notes", search_kwargs={"top_k": 5})
    
    # Combine retrievers in a chain
    combined_docs = exam_retriever.get_relevant_documents(query) + \\
                    notes_retriever.get_relevant_documents(query)
"""
