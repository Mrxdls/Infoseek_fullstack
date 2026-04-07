"""
ExamProcessor — extracts structured question data from university exam PDFs.
Uses Gemini Pro with EXTRACTION_PROMPT to produce consistent JSON output.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import structlog

from app.services.llm.gemini_client import GeminiClient

logger = structlog.get_logger()

# ── Extraction Prompt ──────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an expert academic document parser specializing in university examination papers.

Your task is to extract structured information from the following exam paper text and return it as valid JSON.

Extract the following:

1. **metadata** - Document-level information:
   - subject_name: Full subject/course name
   - subject_code: Subject/course code (e.g., CS101, BCA301)
   - exam_type: Type of exam (e.g., "End Semester", "Mid Term", "Internal Assessment")
   - university: University/institution name
   - program: Degree program (e.g., BCA, MCA, B.Tech, MBA)
   - semester: Semester number (e.g., "3", "5")
   - academic_year: Academic year (e.g., "2023-24")
   - max_marks: Total marks for the exam
   - duration: Exam duration (e.g., "3 Hours")
   - date: Exam date if present

2. **exam_pattern** - Structure of the exam:
   - parts: Array of exam sections/parts (e.g., ["Part A", "Part B", "Part C"])
   - marks_per_part: Object mapping part name to marks (e.g., {"Part A": 20, "Part B": 30})
   - instructions: Key instructions (max 3 bullet points as strings)

3. **questions** - Array of all questions:
   Each question must have:
   - part: Which section/part this belongs to (e.g., "Part A", "Part B", or "General")
   - question_no: Question number as string (e.g., "1", "2a", "3i")
   - marks: Marks allocated as integer
   - question_type: One of: "short_answer", "long_answer", "essay", "problem", "mcq", "fill_blank", "true_false", "match", "definition", "application"
   - text: Full question text, including any sub-questions

Rules:
- Include ALL questions — do not skip any
- For multi-part questions (a, b, c), include each sub-part as a separate entry with appropriate question_no
- Preserve mathematical notation and technical terms exactly as written
- If a field cannot be determined, use null
- Return ONLY the JSON object, no explanation

Exam paper text:
{text}

Return a single JSON object with keys: metadata, exam_pattern, questions"""


@dataclass
class ExamQuestion:
    part: str
    question_no: str
    marks: int
    question_type: str
    text: str


@dataclass
class ExamExtractionResult:
    metadata: dict = field(default_factory=dict)
    exam_pattern: dict = field(default_factory=dict)
    questions: List[ExamQuestion] = field(default_factory=list)
    subject_name: Optional[str] = None
    subject_code: Optional[str] = None


class ExamProcessor:
    """
    Processes university exam PDFs using Gemini Pro + structured extraction.
    Returns structured question data ready for chunking and embedding.
    """

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self._gemini = gemini_client or GeminiClient()

    def process(self, text: str) -> ExamExtractionResult:
        """
        Extract structured data from exam text.
        Uses Gemini Pro with EXTRACTION_PROMPT → parses JSON → returns ExamExtractionResult.
        """
        prompt = EXTRACTION_PROMPT.format(text=text[:50_000])  # cap at 50k chars
        raw = self._gemini.generate_json(
            prompt=prompt,
            model=self._gemini._large,
            max_tokens=8192,
        )

        if not raw:
            logger.warning("ExamProcessor: empty response from Gemini")
            return ExamExtractionResult()

        questions = []
        for q in raw.get("questions", []):
            questions.append(ExamQuestion(
                part=q.get("part") or "General",
                question_no=str(q.get("question_no") or ""),
                marks=int(q.get("marks") or 0),
                question_type=q.get("question_type") or "short_answer",
                text=q.get("text") or "",
            ))

        metadata = raw.get("metadata", {})
        result = ExamExtractionResult(
            metadata=metadata,
            exam_pattern=raw.get("exam_pattern", {}),
            questions=questions,
            subject_name=metadata.get("subject_name"),
            subject_code=metadata.get("subject_code"),
        )

        logger.info(
            "Exam extracted",
            subject=result.subject_name,
            questions=len(questions),
        )
        return result

    async def aprocess(self, text: str) -> ExamExtractionResult:
        import asyncio
        return await asyncio.to_thread(self.process, text)
