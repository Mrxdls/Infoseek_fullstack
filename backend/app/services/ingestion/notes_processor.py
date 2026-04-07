"""
NotesProcessor — processes lecture note PDFs into structured page chunks.
Uses Gemini Flash to auto-detect subject and semester from the first page.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

import structlog

from app.services.ingestion.extractor import DocumentExtractor, PageResult
from app.services.llm.gemini_client import GeminiClient

logger = structlog.get_logger()

_SUBJECT_DETECT_PROMPT = """Analyze the following text from the first page of lecture notes and extract:
1. subject: The full subject/course name
2. subject_code: The subject/course code (if visible)
3. semester: The semester number as a string (e.g., "3", "5", "III")
4. program: The degree program if mentioned (e.g., BCA, MCA, B.Tech)

Return ONLY a JSON object with these four keys. Use null for any field not found.

Text:
{text}"""


@dataclass
class NoteChunk:
    page_number: int
    content: str
    subject: Optional[str] = None
    semester: Optional[str] = None
    chunk_index: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class NotesExtractionResult:
    chunks: List[NoteChunk] = field(default_factory=list)
    subject: Optional[str] = None
    semester: Optional[str] = None
    page_count: int = 0


class NotesProcessor:
    """
    Processes lecture note PDFs:
    1. Extracts text per page (digital + Vision fallback via DocumentExtractor)
    2. Detects subject + semester from first page via Gemini Flash
    3. Returns list of NoteChunk objects ready for embedding
    """

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self._gemini = gemini_client or GeminiClient()
        self._extractor = DocumentExtractor()

    def process(self, content: bytes, filename: str) -> NotesExtractionResult:
        extraction = self._extractor.extract(content, filename)
        pages = extraction.pages

        # Fall back to splitting full text into synthetic pages if no page-level data
        if not pages:
            pages = self._split_text_to_pages(extraction.text)

        subject, semester = self._detect_subject_semester(pages)

        chunks = []
        for idx, page in enumerate(pages):
            if not page.text.strip():
                continue
            chunks.append(NoteChunk(
                page_number=page.page_number,
                content=page.text,
                subject=subject,
                semester=semester,
                chunk_index=idx,
                metadata={"is_ocr": page.is_ocr},
            ))

        logger.info(
            "Notes processed",
            filename=filename,
            subject=subject,
            semester=semester,
            chunks=len(chunks),
        )
        return NotesExtractionResult(
            chunks=chunks,
            subject=subject,
            semester=semester,
            page_count=extraction.page_count,
        )

    async def aprocess(self, content: bytes, filename: str) -> NotesExtractionResult:
        import asyncio
        return await asyncio.to_thread(self.process, content, filename)

    def _detect_subject_semester(self, pages: List[PageResult]) -> tuple[Optional[str], Optional[str]]:
        """Use Gemini Flash to extract subject and semester from the first 2 pages."""
        if not pages:
            return None, None

        first_pages_text = "\n\n".join(p.text for p in pages[:2] if p.text)[:4000]
        if not first_pages_text.strip():
            return None, None

        result = self._gemini.generate_json(
            prompt=_SUBJECT_DETECT_PROMPT.format(text=first_pages_text),
            model=self._gemini._small,
            max_tokens=512,
        )

        subject = result.get("subject")
        semester = result.get("semester")

        if subject:
            subject = subject.strip()
        if semester:
            # Normalize Roman numerals to Arabic
            roman_map = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5",
                         "VI": "6", "VII": "7", "VIII": "8"}
            semester = roman_map.get(semester.strip().upper(), semester.strip())

        logger.info("Subject detected", subject=subject, semester=semester)
        return subject, semester

    @staticmethod
    def _split_text_to_pages(text: str, chars_per_page: int = 3000) -> List[PageResult]:
        """Fallback: split full text into synthetic pages for non-PDF files."""
        chunks = [text[i:i + chars_per_page] for i in range(0, len(text), chars_per_page)]
        return [
            PageResult(page_number=i + 1, text=chunk)
            for i, chunk in enumerate(chunks)
            if chunk.strip()
        ]
