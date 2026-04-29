"""
Chunking strategies — LangChain-based text splitting.

- NotesChunker: structure-aware chunking using LangChain RecursiveCharacterTextSplitter
- ExamChunker: wraps ExamProcessor output into Chunk objects (one chunk per question)
- OCRAdaptedChunker: smaller chunks + higher overlap for OCR-derived text (LangChain-based)
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

import structlog
from langchain.text_splitter import RecursiveCharacterTextSplitter

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
    """Base chunker using LangChain RecursiveCharacterTextSplitter."""

    def __init__(self, chunk_size: int = None, overlap: int = None):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap = overlap or settings.CHUNK_OVERLAP
        self._splitter = None

    @property
    def splitter(self) -> RecursiveCharacterTextSplitter:
        """Lazy-initialize LangChain text splitter."""
        if self._splitter is None:
            self._splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.overlap,
                separators=["\n\n", "\n", " ", ""],  # Default priority order
                length_function=len,
            )
        return self._splitter

    def _split_text(self, text: str, separators: list = None) -> List[str]:
        """Split text using LangChain splitter with optional custom separators."""
        if separators:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.overlap,
                separators=separators,
                length_function=len,
            )
        else:
            splitter = self.splitter

        return splitter.split_text(text)


class NotesChunker(BaseChunker):
    """
    Structure-aware chunking for lecture notes using LangChain RecursiveCharacterTextSplitter.
    Respects headings, paragraphs, and line breaks as natural boundaries.
    """

    def chunk(
        self,
        text: str,
        document_type: DocumentType = DocumentType.NOTES,
        subject_name: Optional[str] = None,
        subject_code: Optional[str] = None,
    ) -> List[Chunk]:
        """
        Chunk notes using LangChain splitter with structure-aware separators.
        Priority: Paragraphs → Lines → Words → Characters
        """
        # Structure-aware separators for notes (heading patterns included)
        separators = [
            "\n\n",                              # Paragraphs (primary)
            "(?:^|\n)#{1,6}\s+.+$",              # Markdown headers (via regex)
            "\n",                                # Lines
            " ",                                 # Words
            "",                                  # Characters
        ]

        # Use LangChain splitter with structure-aware separators
        text_chunks = self._split_text(text, separators=separators)

        # Convert to Chunk objects
        chunks = []
        for idx, chunk_text in enumerate(text_chunks):
            if chunk_text.strip():
                chunks.append(Chunk(
                    chunk_text=chunk_text.strip(),
                    chunk_index=idx,
                    subject_name=subject_name,
                    subject_code=subject_code,
                    document_type=document_type,
                    priority=1.0,
                ))

        logger.info(
            "Notes chunked (LangChain)",
            total_chunks=len(chunks),
            chunk_size=self.chunk_size,
            overlap=self.overlap,
        )
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
    """
    LangChain-based chunking optimized for OCR-derived text.
    Smaller chunks (256 tokens) + higher overlap (64) to handle OCR noise.
    """

    def __init__(self):
        super().__init__(chunk_size=256, overlap=64)

    def chunk(
        self,
        text: str,
        document_type: DocumentType = DocumentType.NOTES,
        **kwargs,
    ) -> List[Chunk]:
        """
        Chunk OCR text with smaller chunks and higher overlap.
        Separator priority: Paragraphs → Lines → Words → Characters
        """
        # For OCR text, respect paragraph breaks but allow smaller chunks
        separators = [
            "\n\n",   # Paragraphs
            "\n",     # Lines
            " ",      # Words
            "",       # Characters
        ]

        text_chunks = self._split_text(text, separators=separators)

        chunks = []
        for idx, chunk_text in enumerate(text_chunks):
            if chunk_text.strip():
                chunks.append(Chunk(
                    chunk_text=chunk_text.strip(),
                    chunk_index=idx,
                    document_type=document_type,
                    priority=0.8,  # Slightly lower priority for OCR chunks
                    metadata={"source": "ocr"},
                ))

        logger.info(
            "OCR document chunked (LangChain)",
            total_chunks=len(chunks),
            chunk_size=256,
            overlap=64,
        )
        return chunks


class ChunkerFactory:
    """Selects chunking strategy based on document type and OCR status."""

    @staticmethod
    def get_notes_chunker(is_ocr: bool = False) -> BaseChunker:
        return OCRAdaptedChunker() if is_ocr else NotesChunker()

    @staticmethod
    def get_exam_chunker() -> ExamChunker:
        return ExamChunker()
