"""
Document management endpoints.
Upload, status polling, listing, and deletion.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import limiter, AUTH_RATE, UPLOAD_RATE
from app.db.models.models import Document, DocumentChunk, DocumentStatus, DocumentType, User, UserRole
from app.db.session import get_db
from app.schemas.schemas import DocumentListResponse, DocumentStatusResponse, DocumentUploadResponse
from app.services.auth.auth_service import get_current_user, get_current_active_admin
from app.services.ingestion.gcs_service import GCSService
from app.tasks.celery_app import process_document

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _validate_file(file: UploadFile) -> None:
    import os
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not supported. Allowed: {ALLOWED_EXTENSIONS}",
        )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
@limiter.limit(UPLOAD_RATE)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    subject_name: Optional[str] = Form(None),
    subject_code: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Upload and queue a document for processing. Admin/Staff only."""
    _validate_file(file)

    gcs = GCSService()
    gcs_result = await gcs.upload_document(file, str(current_user.id))

    doc = Document(
        uploaded_by_id=current_user.id,
        filename=gcs_result["filename"],
        gcs_key=gcs_result["gcs_key"],
        file_size_bytes=gcs_result["file_size_bytes"],
        document_type=document_type,
        subject_name=subject_name,
        subject_code=subject_code,
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    await db.flush()

    # Dispatch Celery task
    task = process_document.delay(str(doc.id))
    doc.task_id = task.id
    await db.commit()

    return DocumentUploadResponse(
        document_id=doc.id,
        filename=doc.filename,
        document_type=document_type,
        status=DocumentStatus.PENDING,
        task_id=task.id,
        message="Document queued for processing.",
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
@limiter.limit(AUTH_RATE)
async def get_document_status(
    request: Request,
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Count chunks
    chunk_count_result = await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
    )
    chunk_count = chunk_count_result.scalar()

    return DocumentStatusResponse(
        document_id=doc.id,
        status=doc.status.value,
        filename=doc.filename,
        document_type=doc.document_type,
        subject_name=doc.subject_name,
        subject_code=doc.subject_code,
        page_count=doc.page_count,
        chunk_count=chunk_count,
        created_at=doc.created_at,
        error_message=doc.error_message,
    )


@router.get("/", response_model=DocumentListResponse)
@limiter.limit(AUTH_RATE)
async def list_documents(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    document_type: Optional[DocumentType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Document)
    if document_type:
        query = query.where(Document.document_type == document_type)
    query = query.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    docs = result.scalars().all()

    total_result = await db.execute(select(func.count(Document.id)))
    total = total_result.scalar()

    doc_responses = []
    for doc in docs:
        chunk_count_result = await db.execute(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc.id)
        )
        doc_responses.append(
            DocumentStatusResponse(
                document_id=doc.id,
                status=doc.status.value,
                filename=doc.filename,
                document_type=doc.document_type,
                subject_name=doc.subject_name,
                subject_code=doc.subject_code,
                page_count=doc.page_count,
                chunk_count=chunk_count_result.scalar(),
                created_at=doc.created_at,
                error_message=doc.error_message,
            )
        )

    return DocumentListResponse(documents=doc_responses, total=total, page=page, page_size=page_size)


@router.delete("/{document_id}", status_code=204)
@limiter.limit(AUTH_RATE)
async def delete_document(
    request: Request,
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Delete document, its chunks/notes from DB, and the file from GCS. Admin only."""
    from app.services.ingestion.vector_store import VectorStoreService

    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove embeddings from pgvector tables
    vs = VectorStoreService()
    await vs.delete_by_document_id(db, str(document_id))

    # Remove file from GCS
    gcs = GCSService()
    gcs.delete_object(doc.gcs_key)

    # DB cascade deletes chunks + notes
    await db.delete(doc)
    return None
