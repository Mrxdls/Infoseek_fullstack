"""
S3 storage service for document uploads.
"""

import uuid
from pathlib import Path

import boto3
import structlog
from botocore.exceptions import ClientError
from fastapi import UploadFile

from app.core.config import settings

logger = structlog.get_logger()


class S3Service:
    def __init__(self):
        self._client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        self.bucket = settings.S3_BUCKET_NAME

    def _generate_key(self, user_id: str, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        unique = uuid.uuid4().hex
        return f"documents/{user_id}/{unique}{ext}"

    async def upload_document(self, file: UploadFile, user_id: str) -> dict:
        """Upload document to S3 and return key + metadata."""
        content = await file.read()
        key = self._generate_key(user_id, file.filename)

        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=file.content_type or "application/octet-stream",
                Metadata={"original_filename": file.filename, "uploaded_by": user_id},
            )
        except ClientError as e:
            logger.error("S3 upload failed", error=str(e), key=key)
            raise

        logger.info("Document uploaded to S3", key=key, size=len(content))
        return {"s3_key": key, "file_size_bytes": len(content), "filename": file.filename}

    def generate_presigned_url(self, s3_key: str, expiry: int = 3600) -> str:
        """Generate a pre-signed URL for temporary access."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=expiry,
        )

    def download_to_bytes(self, s3_key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=s3_key)
        return response["Body"].read()

    def delete_object(self, s3_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=s3_key)
        except ClientError as e:
            logger.warning("S3 delete failed", error=str(e), key=s3_key)
