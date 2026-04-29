"""
Document text extraction pipeline — LangChain-based loaders with Vision OCR fallback.
Supports: Digital PDFs (PyPDFLoader), Scanned PDFs (Vision OCR), DOCX, Markdown, TXT.
Strategy: digital-first, per-page Vision API fallback if text is sparse.
"""

import io
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import structlog
from google.cloud import vision
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredLoader,
)

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
    Digital-first extraction with per-page Vision API fallback (LangChain PyPDFLoader).
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
        """
        Extract PDF using LangChain PyPDFLoader with Vision OCR fallback for sparse pages.
        """
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            # Load PDF using LangChain PyPDFLoader
            loader = PyPDFLoader(temp_path)
            lc_documents = loader.load()  # Returns List[Document]

            pages: List[PageResult] = []
            any_ocr = False

            for doc in lc_documents:
                digital_text = doc.page_content.strip()
                page_num = doc.metadata.get("page", 0) + 1

                if len(digital_text) >= _OCR_TEXT_THRESHOLD:
                    # Good extraction from PyPDF
                    pages.append(PageResult(
                        page_number=page_num,
                        text=digital_text,
                        is_ocr=False,
                    ))
                else:
                    # Sparse page — fall back to Vision OCR
                    logger.debug(
                        "Page sparse, using Vision OCR",
                        page=page_num,
                        chars=len(digital_text),
                    )
                    ocr_text = self._ocr_page_from_pdf(temp_path, page_num - 1)
                    any_ocr = True
                    pages.append(PageResult(
                        page_number=page_num,
                        text=ocr_text,
                        is_ocr=True,
                    ))

            full_text = "\n\n".join(p.text for p in pages if p.text)
            logger.info(
                "PDF extracted",
                pages=len(lc_documents),
                ocr_pages=sum(1 for p in pages if p.is_ocr),
                method="langchain_pypdf_vision_hybrid",
            )
            return TextExtractorResult(
                text=full_text,
                page_count=len(lc_documents),
                is_ocr=any_ocr,
                pages=pages,
                metadata={"extraction_method": "langchain_pypdf_vision_hybrid"},
            )
        finally:
            os.unlink(temp_path)

    def _ocr_page_from_pdf(self, pdf_path: str, page_index: int) -> str:
        """
        Render page to PNG and run Google Vision document_text_detection.
        Uses fitz for rendering (minimal, only for OCR pages).
        """
        import fitz  # Import only when needed (OCR fallback)

        try:
            doc = fitz.open(pdf_path)
            page = doc[page_index]
            mat = fitz.Matrix(200 / 72, 200 / 72)  # 200 DPI
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            doc.close()

            vision_image = vision.Image(content=img_bytes)
            response = self._vision.document_text_detection(image=vision_image)

            if response.error.message:
                logger.warning("Vision OCR error", error=response.error.message)
                return ""
            return response.full_text_annotation.text or ""
        except Exception as e:
            logger.error("Vision OCR page rendering failed", error=str(e), page=page_index)
            return ""


class DocxExtractor:
    """
    Extract DOCX using LangChain UnstructuredLoader (more robust than python-docx).
    """

    def extract(self, content: bytes) -> TextExtractorResult:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            # Use LangChain's UnstructuredLoader for DOCX
            loader = UnstructuredLoader(temp_path)
            lc_documents = loader.load()

            # Combine all document text
            text = "\n\n".join([doc.page_content for doc in lc_documents])

            logger.info(
                "DOCX extracted",
                pages=len(lc_documents),
                method="langchain_unstructured",
            )
            return TextExtractorResult(
                text=text,
                page_count=len(lc_documents),
                is_ocr=False,
                metadata={"extraction_method": "langchain_unstructured"},
            )
        except Exception as e:
            logger.error("DOCX extraction failed, falling back to python-docx", error=str(e))
            # Fallback to simple python-docx extraction
            return self._fallback_docx_extract(content)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @staticmethod
    def _fallback_docx_extract(content: bytes) -> TextExtractorResult:
        """Fallback DOCX extraction using python-docx."""
        try:
            from docx import Document as DocxDocument

            doc = DocxDocument(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n\n".join(paragraphs)

            logger.info("DOCX extracted (fallback)", sections=len(doc.sections), method="python_docx")
            return TextExtractorResult(
                text=text,
                page_count=len(doc.sections),
                is_ocr=False,
                metadata={"extraction_method": "python_docx_fallback"},
            )
        except Exception as e:
            logger.error("DOCX fallback extraction failed", error=str(e))
            return TextExtractorResult(
                text="",
                page_count=0,
                is_ocr=False,
                metadata={"extraction_method": "docx_failed"},
            )


class PlainTextExtractor:
    """
    Extract plain text (TXT, Markdown) using LangChain TextLoader.
    """

    def extract(self, content: bytes) -> TextExtractorResult:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="wb") as f:
            f.write(content)
            temp_path = f.name

        try:
            # Use LangChain's TextLoader
            loader = TextLoader(temp_path, encoding="utf-8")
            lc_documents = loader.load()

            # Extract text
            text = "\n\n".join([doc.page_content for doc in lc_documents])

            # Estimate page count (1 page ≈ 3000 chars)
            page_count = max(1, len(text) // 3000)

            logger.info(
                "Plain text extracted",
                chars=len(text),
                pages=page_count,
                method="langchain_textloader",
            )
            return TextExtractorResult(
                text=text,
                page_count=page_count,
                is_ocr=False,
                metadata={"extraction_method": "langchain_textloader"},
            )
        except Exception as e:
            logger.error("Plain text extraction failed", error=str(e))
            # Fallback: manual decode
            try:
                text = content.decode("utf-8", errors="replace")
                page_count = max(1, len(text) // 3000)
                return TextExtractorResult(
                    text=text,
                    page_count=page_count,
                    is_ocr=False,
                    metadata={"extraction_method": "plaintext_fallback"},
                )
            except Exception as e2:
                logger.error("Plain text fallback extraction failed", error=str(e2))
                return TextExtractorResult(
                    text="",
                    page_count=0,
                    is_ocr=False,
                    metadata={"extraction_method": "plaintext_failed"},
                )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class DocumentExtractor:
    """
    Factory — selects the right LangChain extractor based on file extension.
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
            raise ValueError(f"Unsupported file type: {ext}. Supported: {', '.join(self._EXTRACTORS.keys())}")

        logger.info("Starting extraction", filename=filename, file_type=ext)

        try:
            result = extractor_cls().extract(content)
        except Exception as e:
            logger.error("Extraction failed", filename=filename, error=str(e))
            raise

        # Clean extracted text
        result.text = self._clean_text(result.text)
        for page in result.pages:
            page.text = self._clean_text(page.text)

        logger.info(
            "Text extracted successfully",
            filename=filename,
            chars=len(result.text),
            pages=result.page_count,
            method=result.metadata.get("extraction_method"),
        )
        return result

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalize and clean extracted text."""
        # Convert CRLF to LF
        text = re.sub(r"\r\n", "\n", text)
        # Normalize multiple spaces/tabs to single space
        text = re.sub(r"[ \t]{2,}", " ", text)
        # Normalize multiple newlines (max 2)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove trailing spaces from lines
        text = re.sub(r"[^\S\n]+", " ", text)
        # Remove non-printable characters (except newline and unicode)
        text = re.sub(r"[^\x20-\x7E\n\u00A0-\uFFFF]", "", text)
        return text.strip()
