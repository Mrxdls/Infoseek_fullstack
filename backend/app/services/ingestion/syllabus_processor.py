"""
SyllabusProcessor — extracts structured subject data from university syllabus PDFs.

Strategy:
  - Scan pages digitally (PyMuPDF)
  - Detect subject boundaries via subject-code regex (e.g. 5CAI3-01:)
  - Group all pages belonging to each subject (main + continuation pages)
  - Skip pure filler pages (cover/divider pages with no subject code and very little text)
  - Run SYLLABUS_EXTRACTION_PROMPT on each subject group via Gemini Flash
  - Return list of SyllabusRecord objects
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
import structlog

from app.services.llm.gemini_client import GeminiClient

logger = structlog.get_logger()

# Matches codes like 5CAI3-01, 6AID5-12, 4AID4-07
_SUBJECT_CODE_RE = re.compile(r"\b\d[A-Z]{2,5}\d-\d{2}\b")
_FILLER_THRESHOLD = 400  # chars — pages below this with no subject code are skipped


SYLLABUS_EXTRACTION_PROMPT = """You are an expert at extracting structured data from university syllabus documents.

You will receive raw text from a university syllabus page.
Return ONLY a valid raw JSON object. No markdown. No backticks. No explanation.
If a field cannot be found, use null. Never guess or hallucinate.

============================
FIELD BY FIELD INSTRUCTIONS
============================

--- university ---
Full university name from the top header.
Example: "Rajasthan Technical University, Kota"

--- session ---
Academic session text if present.
Example: "2021-22 onwards"

--- subject_code ---
The code appearing immediately before the subject name.
Pattern: "4AID4-07: Data Communication..."
Extract: "4AID4-07"

--- subject_name ---
Full subject name after the subject code and colon.
Pattern: "4AID4-07: Data Communication and Computer Networks"
Extract: "Data Communication and Computer Networks"

--- course ---
Degree name only. Clean value:
"B.Tech" / "M.Tech" / "BCA" / "MCA" / "B.Sc"
Look for: "B.Tech. Artificial Intelligence" → "B.Tech"

--- branch ---
Full branch/specialization name.
Look for: "II Year-IV Semester: B.Tech. Artificial Intelligence and Data Science"
Extract: "Artificial Intelligence and Data Science"

--- year ---
Study year as integer.
"II Year" → 2, "III Year" → 3, "I Year" → 1

--- semester ---
Always integer. Convert Roman numerals.
"IV Semester" → 4, "VI-Sem" → 6, "V Semester" → 5

--- credits ---
Number from "Credit: 3" → 3

--- max_marks ---
Integer from "Max. Marks: 100" → 100

--- internal_marks ---
Integer from "IA:30" → 30

--- external_marks ---
Integer from "ETE:70" → 70

--- lecture_hours ---
Exactly as written: "3L+0T+0P"

--- total_hours ---
Integer from Total row at bottom of syllabus table.
"Total 40" → 40

--- duration_hours ---
Number from "End Term Exam: 3 Hours" → 3

--- units ---
Array of unit objects from the syllabus content table.
Each numbered row is one unit.

For each unit:
  unit_no: Integer from SN column. 1, 2, 3...
  unit_title: The main heading of that unit (first bold phrase before first colon or comma).
  topics: Array of individual topics from that unit's content. Split by comma carefully. Keep full technical terms intact.
  hours: Integer from the Hours column for that row.
  raw_content: Complete verbatim text of that unit cell exactly as it appears.

============================
STRICT RULES
============================
- Return ONLY the JSON object. Nothing else. No markdown.
- semester and year MUST be integers, never strings.
- topics MUST be an array, never a single string.
- units MUST include every row from the syllabus table.
- raw_content must be complete, never truncated.

============================
EXACT OUTPUT FORMAT
============================
{
  "metadata": {
    "university": string | null,
    "session": string | null,
    "subject_code": string | null,
    "subject_name": string | null,
    "course": string | null,
    "branch": string | null,
    "year": integer | null,
    "semester": integer | null,
    "credits": number | null,
    "max_marks": integer | null,
    "internal_marks": integer | null,
    "external_marks": integer | null,
    "lecture_hours": string | null,
    "total_hours": integer | null,
    "duration_hours": number | null
  },
  "units": [
    {
      "unit_no": integer,
      "unit_title": string,
      "topics": [string],
      "hours": integer | null,
      "raw_content": string
    }
  ]
}

Syllabus text:
{text}"""


@dataclass
class SyllabusRecord:
    subject_code: Optional[str]
    subject_name: str
    university: Optional[str]
    course: Optional[str]
    branch: Optional[str]
    year: Optional[int]
    semester: Optional[int]
    credits: Optional[float]
    max_marks: Optional[int]
    internal_marks: Optional[int]
    external_marks: Optional[int]
    lecture_hours: Optional[str]
    total_hours: Optional[int]
    duration_hours: Optional[float]
    units: list = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


class SyllabusProcessor:
    """
    Processes university syllabus PDFs.
    Groups pages by subject, extracts structured data per subject using Gemini Flash.
    """

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self._gemini = gemini_client or GeminiClient()

    def process(self, content: bytes) -> List[SyllabusRecord]:
        doc = fitz.open(stream=content, filetype="pdf")
        subject_groups = self._group_pages_by_subject(doc)
        records = []

        for code, pages_text in subject_groups:
            combined = "\n\n".join(pages_text)
            record = self._extract_subject(combined, code)
            if record:
                records.append(record)

        logger.info("Syllabus processed", subjects=len(records))
        return records

    async def aprocess(self, content: bytes) -> List[SyllabusRecord]:
        import asyncio
        return await asyncio.to_thread(self.process, content)

    def _group_pages_by_subject(self, doc: fitz.Document) -> List[Tuple[Optional[str], List[str]]]:
        """
        Returns list of (subject_code, [page_texts]) groups.
        A new group starts whenever a page contains a subject code.
        Pure filler pages (no code + below threshold) are skipped.
        """
        groups: List[Tuple[Optional[str], List[str]]] = []
        current_code: Optional[str] = None
        current_pages: List[str] = []

        for page in doc:
            text = page.get_text("text").strip()
            codes = _SUBJECT_CODE_RE.findall(text)

            if codes:
                # New subject starts here
                if current_pages:
                    groups.append((current_code, current_pages))
                current_code = codes[0]
                current_pages = [text]
            elif len(text) < _FILLER_THRESHOLD and not current_pages:
                # Filler page before any subject — skip
                continue
            elif current_pages:
                # Continuation page for current subject
                current_pages.append(text)
            # else: filler page before first subject — skip

        if current_pages:
            groups.append((current_code, current_pages))

        logger.info("Subject groups found", count=len(groups))
        return groups

    def _extract_subject(self, text: str, detected_code: Optional[str]) -> Optional[SyllabusRecord]:
        """Run Gemini Flash + SYLLABUS_EXTRACTION_PROMPT on one subject's text."""
        prompt = SYLLABUS_EXTRACTION_PROMPT.replace("{text}", text[:8000])
        raw = self._gemini.generate_json(
            prompt=prompt,
            model=self._gemini._small,
            max_tokens=8192,
        )

        if not raw:
            logger.warning("Syllabus extraction returned empty", code=detected_code)
            return None

        meta = raw.get("metadata", {})
        subject_name = meta.get("subject_name") or ""
        if not subject_name:
            logger.warning("No subject name extracted", code=detected_code)
            return None

        units = raw.get("units", [])
        # Normalise units
        clean_units = []
        for u in units:
            clean_units.append({
                "unit_no": u.get("unit_no"),
                "unit_title": u.get("unit_title", ""),
                "topics": u.get("topics", []) if isinstance(u.get("topics"), list) else [],
                "hours": u.get("hours"),
                "raw_content": u.get("raw_content", ""),
            })

        record = SyllabusRecord(
            subject_code=meta.get("subject_code") or detected_code,
            subject_name=subject_name,
            university=meta.get("university"),
            course=meta.get("course"),
            branch=meta.get("branch"),
            year=_to_int(meta.get("year")),
            semester=_to_int(meta.get("semester")),
            credits=_to_float(meta.get("credits")),
            max_marks=_to_int(meta.get("max_marks")),
            internal_marks=_to_int(meta.get("internal_marks")),
            external_marks=_to_int(meta.get("external_marks")),
            lecture_hours=meta.get("lecture_hours"),
            total_hours=_to_int(meta.get("total_hours")),
            duration_hours=_to_float(meta.get("duration_hours")),
            units=clean_units,
            raw_metadata=meta,
        )
        logger.info("Subject extracted", code=record.subject_code, name=subject_name, units=len(clean_units))
        return record


def _to_int(val) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _to_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
