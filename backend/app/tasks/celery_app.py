"""
Celery application and background tasks.

Tasks:
- process_document: Full ingestion pipeline (dual branch: exam vs notes)
- expire_stale_sessions: Periodic cleanup of temporary sessions
"""

import asyncio

import structlog
from celery import Celery
from celery.schedules import crontab
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = structlog.get_logger()

# ─── Celery Configuration ──────────────────────────────────────────────────────

celery_app = Celery(
    "rag_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,
    task_time_limit=900,
    beat_schedule={
        "expire-sessions-hourly": {
            "task": "app.tasks.celery_app.expire_stale_sessions",
            "schedule": crontab(minute=0),
        },
    },
)

# ─── Sync DB Engine for Celery ────────────────────────────────────────────────

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
sync_engine = create_engine(_sync_db_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=sync_engine)


# ─── Tasks ────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="app.tasks.celery_app.process_document", max_retries=3)
def process_document(self, document_id: str):
    """
    Full document ingestion pipeline.

    Branch A — university_exam:
      1. Download from GCS
      2. Extract text (PyMuPDF + Vision fallback)
      3. ExamProcessor → structured JSON (EXTRACTION_PROMPT + Gemini Pro)
      4. ExamChunker → one Chunk per question
      5. Embed + upsert to document_chunks (pgvector)

    Branch B — notes:
      1. Download from GCS
      2. NotesProcessor → per-page chunks with subject/semester auto-detection
      3. Embed + upsert to notes table (pgvector)
    """
    from app.db.models.models import Document, DocumentChunk, Note, DocumentStatus, DocumentType
    from app.services.ingestion.gcs_service import GCSService
    from app.services.ingestion.extractor import DocumentExtractor
    from app.services.ingestion.exam_processor import ExamProcessor
    from app.services.ingestion.notes_processor import NotesProcessor
    from app.services.ingestion.chunker import ChunkerFactory
    from app.services.llm.gemini_client import GeminiClient
    import json

    db: Session = SyncSession()

    try:
        # ── Fetch document ───────────────────────────────��────────────────────
        doc = db.execute(select(Document).where(Document.id == document_id)).scalar_one_or_none()
        if not doc:
            logger.error("Document not found", document_id=document_id)
            return

        doc.status = DocumentStatus.PROCESSING
        db.commit()

        # ── Download from GCS ─────────────────────────────────────────────────
        gcs = GCSService()
        content = gcs.download_to_bytes(doc.gcs_key)
        logger.info("Downloaded from GCS", key=doc.gcs_key, size=len(content))

        gemini = GeminiClient()

        # ── Branch A: Exam ────────────────────────────────────────────────────
        if doc.document_type in (DocumentType.UNIVERSITY_EXAM, DocumentType.MID_TERM_EXAM):
            extractor = DocumentExtractor()
            extraction = extractor.extract(content, doc.filename)
            doc.page_count = extraction.page_count
            doc.is_ocr_required = extraction.is_ocr

            # Structured extraction via Gemini Pro
            processor = ExamProcessor(gemini)
            exam_result = processor.process(extraction.text)

            # Populate document-level metadata
            if exam_result.subject_name and not doc.subject_name:
                doc.subject_name = exam_result.subject_name
            if exam_result.subject_code and not doc.subject_code:
                doc.subject_code = exam_result.subject_code
            if exam_result.metadata:
                doc.doc_metadata = exam_result.metadata

            if not exam_result.questions:
                doc.status = DocumentStatus.FAILED
                doc.error_message = "No questions extracted from exam paper"
                db.commit()
                return

            # Convert questions → Chunks
            chunker = ChunkerFactory.get_exam_chunker()
            chunks = chunker.from_exam_result(exam_result, doc.document_type)

            # Embed + persist
            texts = [c.chunk_text for c in chunks]
            embeddings = gemini.embed_texts(texts)

            db_chunks = []
            for chunk, embedding in zip(chunks, embeddings):
                db_chunks.append(DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.chunk_text,
                    part=chunk.part,
                    question_no=chunk.question_no,
                    marks=chunk.marks,
                    question_type=chunk.question_type,
                    subject_name=chunk.subject_name,
                    subject_code=chunk.subject_code,
                    document_type=chunk.document_type,
                    priority=chunk.priority,
                    token_count=len(chunk.chunk_text.split()),
                    chunk_metadata=chunk.metadata,
                    embedding=embedding,
                ))

            db.add_all(db_chunks)
            logger.info("Exam chunks saved", document_id=document_id, count=len(db_chunks))

        # ── Branch B: Notes ───────────────────────────────────────────────────
        elif doc.document_type == DocumentType.NOTES:
            processor = NotesProcessor(gemini)
            notes_result = processor.process(content, doc.filename)
            doc.page_count = notes_result.page_count
            doc.is_ocr_required = any(c.metadata.get("is_ocr") for c in notes_result.chunks)

            if notes_result.subject and not doc.subject_name:
                doc.subject_name = notes_result.subject
            if notes_result.semester:
                doc.doc_metadata = {**(doc.doc_metadata or {}), "semester": notes_result.semester}

            if not notes_result.chunks:
                doc.status = DocumentStatus.FAILED
                doc.error_message = "No content extracted from notes"
                db.commit()
                return

            texts = [c.content for c in notes_result.chunks]
            embeddings = gemini.embed_texts(texts)

            db_notes = []
            for note, embedding in zip(notes_result.chunks, embeddings):
                db_notes.append(Note(
                    document_id=document_id,
                    chunk_index=note.chunk_index,
                    page_number=note.page_number,
                    content=note.content,
                    subject=note.subject,
                    semester=note.semester,
                    chunk_metadata=note.metadata,
                    embedding=embedding,
                ))

            db.add_all(db_notes)
            logger.info("Note chunks saved", document_id=document_id, count=len(db_notes))

        # ── Branch C: Syllabus ────────────────────────────────────────────────
        elif doc.document_type == DocumentType.SYLLABUS:
            from app.services.ingestion.syllabus_processor import SyllabusProcessor
            from app.db.models.models import Syllabus

            processor = SyllabusProcessor(gemini)
            records = processor.process(content)

            if not records:
                doc.status = DocumentStatus.FAILED
                doc.error_message = "No subjects extracted from syllabus"
                db.commit()
                return

            db_syllabus = []
            for rec in records:
                db_syllabus.append(Syllabus(
                    document_id=document_id,
                    subject_code=rec.subject_code,
                    subject_name=rec.subject_name,
                    university=rec.university,
                    course=rec.course,
                    branch=rec.branch,
                    year=rec.year,
                    semester=rec.semester,
                    credits=rec.credits,
                    max_marks=rec.max_marks,
                    internal_marks=rec.internal_marks,
                    external_marks=rec.external_marks,
                    lecture_hours=rec.lecture_hours,
                    total_hours=rec.total_hours,
                    duration_hours=rec.duration_hours,
                    units=rec.units,
                    raw_metadata=rec.raw_metadata,
                ))

            db.add_all(db_syllabus)
            logger.info("Syllabus subjects saved", document_id=document_id, count=len(db_syllabus))

        else:
            logger.warning("Unknown document type, skipping ingestion", dtype=doc.document_type)
            doc.status = DocumentStatus.FAILED
            doc.error_message = f"Unsupported document type: {doc.document_type}"
            db.commit()
            return

        doc.status = DocumentStatus.INDEXED
        db.commit()
        logger.info("Document ingestion complete", document_id=document_id)

    except Exception as exc:
        db.rollback()
        doc_lookup = db.execute(select(Document).where(Document.id == document_id)).scalar_one_or_none()
        if doc_lookup:
            doc_lookup.status = DocumentStatus.FAILED
            doc_lookup.error_message = str(exc)
            db.commit()
        logger.error("Document ingestion failed", document_id=document_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="app.tasks.celery_app.expire_stale_sessions")
def expire_stale_sessions():
    """Periodic task: clean up expired anonymous sessions."""
    from app.db.session import AsyncSessionLocal
    from app.services.session.session_service import SessionService

    async def _run():
        async with AsyncSessionLocal() as db:
            svc = SessionService(db)
            count = await svc.expire_stale_sessions()
            await db.commit()
            return count

    count = asyncio.run(_run())
    logger.info("Expired sessions cleaned", count=count)
    return count
