"""
Document text extraction pipeline.
Supports: Digital PDFs (PyMuPDF), Scanned PDFs (Google Vision OCR), DOCX, Markdown, TXT.
Strategy: digital-first, per-page Vision API fallback if text is sparse.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
import structlog
from docx import Document as DocxDocument
from google.cloud import vision

logger = structlog.get_logger()

_OCR_TEXT_THRESHOLD = 50  # chars per page — below this triggers per-page OCR


@dataclass
class PageResult:
    page_number: int       # 1-based
    text: str
    is_ocr: bool = False


@dataclass
class TextExtractorResult:
    text: str              # full concatenated text
    page_count: int
    is_ocr: bool = False
    pages: List[PageResult] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class PDFExtractor:
    """
    Digital-first extraction with per-page Vision API fallback.
    Each page is checked independently — only sparse pages go to OCR.
    """

    def __init__(self):
        self._vision_client: Optional[vision.ImageAnnotatorClient] = None

    @property
    def _vision(self) -> vision.ImageAnnotatorClient:
        if self._vision_client is None:
            self._vision_client = vision.ImageAnnotatorClient()
        return self._vision_client

    def extract(self, content: bytes) -> TextExtractorResult:
        doc = fitz.open(stream=content, filetype="pdf")
        page_count = len(doc)
        pages: List[PageResult] = []
        any_ocr = False

        for page_num, page in enumerate(doc):
            digital_text = page.get_text("text").strip()

            if len(digital_text) >= _OCR_TEXT_THRESHOLD:
                pages.append(PageResult(
                    page_number=page_num + 1,
                    text=digital_text,
                    is_ocr=False,
                ))
            else:
                # Sparse page — fall back to Vision OCR
                logger.debug("Page sparse, using Vision OCR", page=page_num + 1, chars=len(digital_text))
                ocr_text = self._ocr_page(page)
                any_ocr = True
                pages.append(PageResult(
                    page_number=page_num + 1,
                    text=ocr_text,
                    is_ocr=True,
                ))

        full_text = "\n\n".join(p.text for p in pages if p.text)
        logger.info(
            "PDF extracted",
            pages=page_count,
            ocr_pages=sum(1 for p in pages if p.is_ocr),
        )
        return TextExtractorResult(
            text=full_text,
            page_count=page_count,
            is_ocr=any_ocr,
            pages=pages,
            metadata={"extraction_method": "pymupdf_vision_hybrid"},
        )

    def _ocr_page(self, page: fitz.Page) -> str:
        """Render page to PNG and run Google Vision document_text_detection."""
        mat = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")

        vision_image = vision.Image(content=img_bytes)
        response = self._vision.document_text_detection(image=vision_image)

        if response.error.message:
            logger.warning("Vision OCR error", error=response.error.message)
            return ""
        return response.full_text_annotation.text or ""


class DocxExtractor:
    def extract(self, content: bytes) -> TextExtractorResult:
        doc = DocxDocument(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs)
        return TextExtractorResult(
            text=text,
            page_count=len(doc.sections),
            is_ocr=False,
            metadata={"extraction_method": "python_docx"},
        )


class PlainTextExtractor:
    def extract(self, content: bytes) -> TextExtractorResult:
        text = content.decode("utf-8", errors="replace")
        page_count = max(1, len(text) // 3000)
        return TextExtractorResult(
            text=text,
            page_count=page_count,
            is_ocr=False,
            metadata={"extraction_method": "plaintext"},
        )


class DocumentExtractor:
    """
    Factory — selects the right extractor based on file extension.
    Normalizes and cleans text output.
    """

    _EXTRACTORS = {
        ".pdf": PDFExtractor,
        ".docx": DocxExtractor,
        ".doc": DocxExtractor,
        ".md": PlainTextExtractor,
        ".txt": PlainTextExtractor,
    }

    def extract(self, content: bytes, filename: str) -> TextExtractorResult:
        ext = Path(filename).suffix.lower()
        extractor_cls = self._EXTRACTORS.get(ext)

        if not extractor_cls:
            raise ValueError(f"Unsupported file type: {ext}")

        result = extractor_cls().extract(content)
        result.text = self._clean_text(result.text)
        for page in result.pages:
            page.text = self._clean_text(page.text)

        logger.info(
            "Text extracted",
            filename=filename,
            chars=len(result.text),
            pages=result.page_count,
            method=result.metadata.get("extraction_method"),
        )
        return result

    @staticmethod
    def _clean_text(text: str) -> str:
        import re
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[^\S\n]+", " ", text)
        text = re.sub(r"[^\x20-\x7E\n\u00A0-\uFFFF]", "", text)
        return text.strip()
