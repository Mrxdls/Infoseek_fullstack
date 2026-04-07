"""
Chunking strategies.

- NotesChunker: structure-aware chunking for lecture notes
- ExamChunker: wraps ExamProcessor output into Chunk objects (one chunk per question)
- OCRAdaptedChunker: smaller chunks + higher overlap for OCR-derived text
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

import structlog

from app.core.config import settings
from app.db.models.models import DocumentType

logger = structlog.get_logger()


@dataclass
class Chunk:
    chunk_text: str
    chunk_index: int
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None
    document_type: DocumentType = DocumentType.NOTES
    priority: float = 1.0
    # Exam-specific fields (None for notes)
    part: Optional[str] = None
    question_no: Optional[str] = None
    marks: Optional[int] = None
    question_type: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class BaseChunker:
    def __init__(self, chunk_size: int = None, overlap: int = None):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap = overlap or settings.CHUNK_OVERLAP

    def _split_by_tokens(self, text: str) -> List[str]:
        """Rough token-aware splitting (1 token ≈ 4 chars)."""
        words = text.split()
        chunks, current, count = [], [], 0

        for word in words:
            word_len = len(word) // 4 + 1
            if count + word_len > self.chunk_size and current:
                chunks.append(" ".join(current))
                overlap_words = current[-(self.overlap // 4):]
                current = overlap_words + [word]
                count = sum(len(w) // 4 + 1 for w in current)
            else:
                current.append(word)
                count += word_len

        if current:
            chunks.append(" ".join(current))
        return chunks


class NotesChunker(BaseChunker):
    """
    Structure-aware chunking for lecture notes.
    Respects headings and paragraphs as natural boundaries.
    """

    _HEADING_RE = re.compile(r"^(#{1,6}\s.+|[A-Z][A-Z\s]{5,}:?)$", re.MULTILINE)

    def chunk(
        self,
        text: str,
        document_type: DocumentType = DocumentType.NOTES,
        subject_name: Optional[str] = None,
        subject_code: Optional[str] = None,
    ) -> List[Chunk]:
        sections = self._HEADING_RE.split(text)
        chunks = []
        idx = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue

            for sub in self._split_by_tokens(section):
                if sub.strip():
                    chunks.append(Chunk(
                        chunk_text=sub.strip(),
                        chunk_index=idx,
                        subject_name=subject_name,
                        subject_code=subject_code,
                        document_type=document_type,
                        priority=1.0,
                    ))
                    idx += 1

        logger.info("Notes chunked", total_chunks=len(chunks))
        return chunks


class ExamChunker:
    """
    Converts ExamProcessor output (structured questions) into Chunk objects.
    One chunk per question — no further splitting needed.
    """

    def from_exam_result(
        self,
        exam_result,  # ExamExtractionResult
        document_type: DocumentType,
    ) -> List[Chunk]:
        """Convert ExamExtractionResult.questions → List[Chunk]."""
        from app.services.ingestion.exam_processor import ExamExtractionResult
        chunks = []
        subject_name = exam_result.subject_name
        subject_code = exam_result.subject_code
        metadata = exam_result.metadata

        for idx, q in enumerate(exam_result.questions):
            # Build readable chunk text with context prefix
            context = f"[Subject: {subject_name or 'N/A'} | Code: {subject_code or 'N/A'} | {q.part} | Q{q.question_no} | {q.marks} marks]\n"
            chunks.append(Chunk(
                chunk_text=context + q.text,
                chunk_index=idx,
                subject_name=subject_name,
                subject_code=subject_code,
                document_type=document_type,
                priority=1.5,  # exam questions get retrieval boost
                part=q.part,
                question_no=q.question_no,
                marks=q.marks,
                question_type=q.question_type,
                metadata={
                    "exam_metadata": metadata,
                    "exam_pattern": exam_result.exam_pattern,
                },
            ))

        logger.info(
            "Exam chunked",
            subject=subject_name,
            total_chunks=len(chunks),
        )
        return chunks


class OCRAdaptedChunker(BaseChunker):
    """Smaller chunks for OCR-derived text which may have noise."""

    def __init__(self):
        super().__init__(chunk_size=256, overlap=64)

    def chunk(
        self,
        text: str,
        document_type: DocumentType = DocumentType.NOTES,
        **kwargs,
    ) -> List[Chunk]:
        paragraphs = re.split(r"\n{2,}", text)
        chunks = []
        idx = 0

        for para in paragraphs:
            for sub in self._split_by_tokens(para.strip()):
                if sub.strip():
                    chunks.append(Chunk(
                        chunk_text=sub.strip(),
                        chunk_index=idx,
                        document_type=document_type,
                        priority=1.0,
                        metadata={"source": "ocr"},
                    ))
                    idx += 1

        logger.info("OCR document chunked", total_chunks=len(chunks))
        return chunks


class ChunkerFactory:
    """Selects chunking strategy based on document type and OCR status."""

    @staticmethod
    def get_notes_chunker(is_ocr: bool = False) -> BaseChunker:
        return OCRAdaptedChunker() if is_ocr else NotesChunker()

    @staticmethod
    def get_exam_chunker() -> ExamChunker:
        return ExamChunker()
