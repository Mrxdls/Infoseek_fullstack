"""
Extended endpoint integration tests to boost coverage.
Covers admin role changes, document upload flow, chat query/stream endpoints,
auth edge cases, and exception handler paths.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.models import (
    Conversation, Document, DocumentChunk, DocumentStatus, DocumentType,
    Message, MessageRole, SessionType, User, UserRole,
)


# ─── Admin Endpoint Extended Tests ───────────────────────────────────────────


class TestAdminEndpointsExtended:
    @pytest.mark.asyncio
    async def test_admin_update_user_role(self, client: AsyncClient, admin_headers: dict):
        # Register a student
        reg_resp = await client.post("/api/v1/auth/register", json={
            "email": f"rolechange_{uuid.uuid4().hex[:6]}@test.com", "password": "pass12345"
        })
        user_id = reg_resp.json()["id"]

        # Change role to staff
        resp = await client.patch(
            f"/api/v1/admin/users/{user_id}/role",
            json={"role": "staff"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "staff"

    @pytest.mark.asyncio
    async def test_admin_cannot_change_own_role(self, client: AsyncClient, admin_headers: dict):
        me = await client.get("/api/v1/auth/me", headers=admin_headers)
        admin_id = me.json()["id"]
        resp = await client.patch(
            f"/api/v1/admin/users/{admin_id}/role",
            json={"role": "student"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_change_role_nonexistent_user(self, client: AsyncClient, admin_headers: dict):
        resp = await client.patch(
            f"/api/v1/admin/users/{uuid.uuid4()}/role",
            json={"role": "staff"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_block_nonexistent_user(self, client: AsyncClient, admin_headers: dict):
        resp = await client.patch(
            f"/api/v1/admin/users/{uuid.uuid4()}/block",
            json={"is_active": False},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_view_conversation(self, client: AsyncClient, admin_headers: dict):
        # Create a conversation as admin
        conv_resp = await client.post(
            "/api/v1/chat/conversations",
            json={"title": "Admin Viewable"},
            headers=admin_headers,
        )
        conv_id = conv_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/admin/conversations/{conv_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["conversation"]["id"] == conv_id

    @pytest.mark.asyncio
    async def test_admin_view_nonexistent_conversation(self, client: AsyncClient, admin_headers: dict):
        resp = await client.get(
            f"/api/v1/admin/conversations/{uuid.uuid4()}",
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ─── Document Upload Extended Tests ──────────────────────────────────────────


class TestDocumentUploadFlow:
    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.documents.process_document")
    @patch("app.api.v1.endpoints.documents.S3Service")
    async def test_upload_document_success(self, mock_s3_cls, mock_task, client: AsyncClient, admin_headers: dict):
        # Mock S3
        mock_s3 = AsyncMock()
        mock_s3.upload_document.return_value = {
            "s3_key": "documents/test.pdf",
            "file_size_bytes": 1024,
            "filename": "test.pdf",
        }
        mock_s3_cls.return_value = mock_s3

        # Mock Celery task
        mock_task.delay.return_value = MagicMock(id="task-123")

        resp = await client.post(
            "/api/v1/documents/upload",
            data={"document_type": "learning_material"},
            files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "test.pdf"
        assert data["task_id"] == "task-123"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    @patch("app.api.v1.endpoints.documents.process_document")
    @patch("app.api.v1.endpoints.documents.S3Service")
    async def test_upload_exam_with_subject(self, mock_s3_cls, mock_task, client: AsyncClient, admin_headers: dict):
        mock_s3 = AsyncMock()
        mock_s3.upload_document.return_value = {
            "s3_key": "documents/exam.pdf",
            "file_size_bytes": 2048,
            "filename": "exam.pdf",
        }
        mock_s3_cls.return_value = mock_s3
        mock_task.delay.return_value = MagicMock(id="task-456")

        resp = await client.post(
            "/api/v1/documents/upload",
            data={
                "document_type": "university_exam",
                "subject_name": "DBMS",
                "subject_code": "CS301",
            },
            files={"file": ("exam.pdf", b"fake pdf", "application/pdf")},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document_type"] == "university_exam"

    @pytest.mark.asyncio
    async def test_get_document_status(self, client: AsyncClient, admin_headers: dict, db_session: AsyncSession):
        # Create a document directly in DB
        me = await client.get("/api/v1/auth/me", headers=admin_headers)
        user_id = me.json()["id"]

        doc = Document(
            uploaded_by_id=uuid.UUID(user_id),
            filename="status_test.pdf",
            s3_key=f"documents/status_{uuid.uuid4().hex}.pdf",
            document_type=DocumentType.LEARNING_MATERIAL,
            status=DocumentStatus.INDEXED,
            page_count=5,
        )
        db_session.add(doc)
        await db_session.commit()

        resp = await client.get(f"/api/v1/documents/{doc.id}/status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "indexed"
        assert data["page_count"] == 5

    @pytest.mark.asyncio
    async def test_list_documents_with_filter(self, client: AsyncClient, admin_headers: dict, db_session: AsyncSession):
        me = await client.get("/api/v1/auth/me", headers=admin_headers)
        user_id = me.json()["id"]

        doc = Document(
            uploaded_by_id=uuid.UUID(user_id),
            filename="filter_test.pdf",
            s3_key=f"documents/filter_{uuid.uuid4().hex}.pdf",
            document_type=DocumentType.UNIVERSITY_EXAM,
            status=DocumentStatus.INDEXED,
        )
        db_session.add(doc)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/documents/?document_type=university_exam",
            headers=admin_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @patch("app.services.ingestion.vector_store.VectorStoreService")
    @patch("app.services.ingestion.s3_service.S3Service")
    async def test_delete_document(self, mock_s3_cls, mock_vs_cls, client: AsyncClient, admin_headers: dict, db_session: AsyncSession):
        me = await client.get("/api/v1/auth/me", headers=admin_headers)
        user_id = me.json()["id"]

        doc = Document(
            uploaded_by_id=uuid.UUID(user_id),
            filename="delete_me.pdf",
            s3_key=f"documents/delete_{uuid.uuid4().hex}.pdf",
            document_type=DocumentType.LEARNING_MATERIAL,
            status=DocumentStatus.INDEXED,
        )
        db_session.add(doc)
        await db_session.commit()

        mock_vs_cls.return_value = MagicMock()
        mock_s3_cls.return_value = MagicMock()

        resp = await client.delete(f"/api/v1/documents/{doc.id}", headers=admin_headers)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_document(self, client: AsyncClient, admin_headers: dict):
        resp = await client.delete(f"/api/v1/documents/{uuid.uuid4()}", headers=admin_headers)
        assert resp.status_code == 404


# ─── Chat Query Extended Tests ───────────────────────────────────────────────


class TestChatQueryExtended:
    @pytest.mark.asyncio
    @patch("app.services.rag.pipeline.openai_client")
    @patch("app.services.rag.pipeline.VectorStoreService")
    @patch("app.utils.cache.get_redis")
    async def test_query_with_cache_hit(self, mock_redis_fn, mock_vs_cls, mock_openai, client: AsyncClient, auth_headers: dict):
        mock_redis = MagicMock()
        cached = {
            "message_id": str(uuid.uuid4()),
            "conversation_id": str(uuid.uuid4()),
            "answer": "Cached answer",
            "sources": [],
            "model_used": "gpt-4o",
            "latency_ms": 50,
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))
        mock_redis_fn.return_value = mock_redis

        # Create conversation
        conv_resp = await client.post(
            "/api/v1/chat/conversations",
            json={"title": "Cache Test"},
            headers=auth_headers,
        )
        conv_id = conv_resp.json()["id"]

        resp = await client.post(
            "/api/v1/chat/query",
            json={"conversation_id": conv_id, "message": "What is SQL?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # OpenAI should NOT have been called
        mock_openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_temporary_conversation(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/api/v1/chat/conversations",
            json={"title": "Temp Conv", "session_type": "temporary"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["session_type"] == "temporary"

    @pytest.mark.asyncio
    async def test_list_conversations_pagination(self, client: AsyncClient, auth_headers: dict):
        # Create a few conversations
        for i in range(3):
            await client.post(
                "/api/v1/chat/conversations",
                json={"title": f"Paginated {i}"},
                headers=auth_headers,
            )

        resp = await client.get(
            "/api/v1/chat/conversations?page=1&page_size=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 2


# ─── Auth Endpoint Extended Tests ────────────────────────────────────────────


class TestAuthEndpointExtended:
    @pytest.mark.asyncio
    async def test_register_returns_correct_fields(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "email": f"fields_{uuid.uuid4().hex[:6]}@test.com",
            "password": "pass12345",
            "full_name": "Full Name",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "email" in data
        assert "role" in data
        assert "is_active" in data
        assert data["full_name"] == "Full Name"

    @pytest.mark.asyncio
    async def test_login_returns_bearer_type(self, client: AsyncClient):
        email = f"bearer_{uuid.uuid4().hex[:6]}@test.com"
        await client.post("/api/v1/auth/register", json={
            "email": email, "password": "pass12345"
        })
        resp = await client.post("/api/v1/auth/login", json={
            "email": email, "password": "pass12345"
        })
        assert resp.json()["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_blocked_user_login(self, client: AsyncClient, admin_headers: dict):
        email = f"blocklogin_{uuid.uuid4().hex[:6]}@test.com"
        reg_resp = await client.post("/api/v1/auth/register", json={
            "email": email, "password": "pass12345"
        })
        user_id = reg_resp.json()["id"]

        # Block the user
        await client.patch(
            f"/api/v1/admin/users/{user_id}/block",
            json={"is_active": False},
            headers=admin_headers,
        )

        # Try to login
        resp = await client.post("/api/v1/auth/login", json={
            "email": email, "password": "pass12345"
        })
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_blocked_user_access_denied(self, client: AsyncClient, admin_headers: dict, db_session: AsyncSession):
        email = f"blockaccess_{uuid.uuid4().hex[:6]}@test.com"
        reg_resp = await client.post("/api/v1/auth/register", json={
            "email": email, "password": "pass12345"
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": email, "password": "pass12345"
        })
        token = login_resp.json()["access_token"]
        user_id = reg_resp.json()["id"]

        # Block via admin
        await client.patch(
            f"/api/v1/admin/users/{user_id}/block",
            json={"is_active": False},
            headers=admin_headers,
        )

        # Try to use token
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


# ─── Exception Handler Tests ─────────────────────────────────────────────────


class TestExceptionHandlers:
    @pytest.mark.asyncio
    async def test_validation_error_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "not-valid",
            "password": "x",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get(f"/api/v1/chat/conversations/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404


# ─── Celery Task Extended Tests ──────────────────────────────────────────────


class TestCeleryTasksExtended:
    @patch("app.services.ingestion.vector_store.VectorStoreService")
    @patch("app.services.ingestion.s3_service.S3Service")
    @patch("app.services.ingestion.extractor.DocumentExtractor")
    @patch("app.services.ingestion.chunker.ChunkerFactory")
    def test_process_document_no_chunks(self, mock_chunker_factory,
                                         mock_extractor_cls, mock_s3_cls, mock_vs_cls):
        from app.tasks.celery_app import process_document

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.document_type = DocumentType.LEARNING_MATERIAL
        mock_doc.subject_name = None
        mock_doc.subject_code = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_doc

        mock_s3_cls.return_value.download_to_bytes.return_value = b"content"
        mock_extraction = MagicMock(text="text", page_count=1, is_ocr=False)
        mock_extractor_cls.return_value.extract.return_value = mock_extraction

        # Chunker returns empty
        mock_chunker = MagicMock()
        mock_chunker.chunk.return_value = []
        mock_chunker_factory.get_chunker.return_value = (mock_chunker, {})

        with patch("app.tasks.celery_app.SyncSession", return_value=mock_db):
            process_document("doc-id")

        assert mock_doc.status == DocumentStatus.FAILED

    @patch("app.services.ingestion.s3_service.S3Service")
    def test_process_document_exception(self, mock_s3_cls):
        from app.tasks.celery_app import process_document

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.document_type = DocumentType.LEARNING_MATERIAL
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_doc

        # S3 download fails
        mock_s3_cls.return_value.download_to_bytes.side_effect = Exception("S3 down")

        with patch("app.tasks.celery_app.SyncSession", return_value=mock_db):
            with pytest.raises(Exception, match="S3 down"):
                process_document("doc-id")

    @patch("app.services.ingestion.vector_store.VectorStoreService")
    @patch("app.services.ingestion.s3_service.S3Service")
    @patch("app.services.ingestion.extractor.DocumentExtractor")
    @patch("app.services.ingestion.chunker.ChunkerFactory")
    @patch("app.services.rag.pipeline.parse_exam_paper_with_ai")
    def test_process_exam_document_with_ai_parse(self, mock_ai_parse, mock_chunker_factory,
                                                   mock_extractor_cls, mock_s3_cls, mock_vs_cls):
        from app.tasks.celery_app import process_document
        from app.services.ingestion.chunker import Chunk

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.document_type = DocumentType.UNIVERSITY_EXAM
        mock_doc.subject_name = None
        mock_doc.subject_code = None
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_doc

        mock_s3_cls.return_value.download_to_bytes.return_value = b"exam content"
        mock_extraction = MagicMock(text="exam text", page_count=2, is_ocr=False)
        mock_extractor_cls.return_value.extract.return_value = mock_extraction

        mock_ai_parse.return_value = {"subject_name": "Physics", "subject_code": "PH101", "questions": []}

        mock_chunker = MagicMock()
        mock_chunks = [Chunk(chunk_text="Q1", chunk_index=0, document_type=DocumentType.UNIVERSITY_EXAM)]
        mock_chunker.chunk.return_value = mock_chunks
        mock_chunker_factory.get_chunker.return_value = (mock_chunker, {})

        mock_vs_cls.return_value.upsert_chunks.return_value = ["pid1"]

        with patch("app.tasks.celery_app.SyncSession", return_value=mock_db):
            process_document("doc-id")

        assert mock_doc.subject_name == "Physics"
        assert mock_doc.subject_code == "PH101"
        assert mock_doc.status == DocumentStatus.INDEXED
