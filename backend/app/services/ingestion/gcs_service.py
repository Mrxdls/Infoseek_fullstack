"""
GCS service — replaces S3Service for document storage.
Uses google-cloud-storage with the project service account.
"""

import os
import uuid
from pathlib import Path
from typing import Optional

import structlog
from fastapi import UploadFile
from google.cloud import storage

from app.core.config import settings

logger = structlog.get_logger()


class GCSService:
    """
    Thin wrapper around GCS for document upload/download/delete.
    Drop-in replacement for the old S3Service — callers see identical method signatures.
    """

    def __init__(self):
        if settings.GOOGLE_APPLICATION_CREDENTIALS:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS
        self._client = storage.Client(project=settings.GCP_PROJECT_ID)
        self._bucket_name = settings.GCS_BUCKET_NAME

    @property
    def _bucket(self):
        return self._client.bucket(self._bucket_name)

    # ── Key generation ───────────────────────────────────────────────────────

    @staticmethod
    def _generate_key(user_id: str, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        unique = uuid.uuid4().hex
        return f"documents/{user_id}/{unique}{ext}"

    # ── Upload ───────────────────────────────────────────────────────────────

    async def upload_document(self, file: UploadFile, user_id: str) -> dict:
        """
        Upload a FastAPI UploadFile to GCS.
        Returns {"gcs_key": str, "file_size_bytes": int, "filename": str}.
        """
        content: bytes = await file.read()
        gcs_key = self._generate_key(user_id, file.filename)
        content_type = file.content_type or "application/octet-stream"

        blob = self._bucket.blob(gcs_key)
        blob.upload_from_string(content, content_type=content_type)

        logger.info("Uploaded to GCS", key=gcs_key, size=len(content))
        return {
            "gcs_key": gcs_key,
            "file_size_bytes": len(content),
            "filename": file.filename,
        }

    # ── Download ─────────────────────────────────────────────────────────────

    def download_to_bytes(self, gcs_key: str) -> bytes:
        """Download a GCS object and return raw bytes."""
        blob = self._bucket.blob(gcs_key)
        content = blob.download_as_bytes()
        logger.info("Downloaded from GCS", key=gcs_key, size=len(content))
        return content

    # ── Delete ───────────────────────────────────────────────────────────────

    def delete_object(self, gcs_key: str) -> None:
        """Delete a GCS object. Silently ignores missing objects."""
        try:
            blob = self._bucket.blob(gcs_key)
            blob.delete()
            logger.info("Deleted from GCS", key=gcs_key)
        except Exception as exc:
            logger.warning("GCS delete failed (may not exist)", key=gcs_key, error=str(exc))

    # ── Signed URL ───────────────────────────────────────────────────────────

    def generate_signed_url(self, gcs_key: str, expiry_seconds: int = 3600) -> str:
        """Generate a temporary signed URL for direct download."""
        import datetime
        blob = self._bucket.blob(gcs_key)
        url = blob.generate_signed_url(
            expiration=datetime.timedelta(seconds=expiry_seconds),
            method="GET",
            version="v4",
        )
        return url
