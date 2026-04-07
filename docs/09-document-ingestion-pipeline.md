# 09 — Document Ingestion Pipeline

This document explains the complete journey from "user clicks Upload" to "chunks are searchable in pgvector". There are three separate processing branches depending on document type.

---

## Overview

```
Upload (FastAPI)
    │
    ├── Save to GCS
    ├── Insert Document row (status=pending)
    ├── Enqueue Celery task
    └── Return 201 immediately
    
Celery Worker picks up task:
    │
    ├── Download from GCS
    │
    ├─[notes]────► NotesProcessor ──► embed pages ──► INSERT notes
    ├─[exam]─────► ExamProcessor ───► embed questions ──► INSERT document_chunks  
    └─[syllabus]─► SyllabusProcessor ──► INSERT syllabus (no embeddings)
```

---

## Stage 0: Upload Handler (`documents.py`)

When an admin or staff member uploads a file, `POST /api/v1/documents/upload` does:

1. **Validates the file** — extension must be `.pdf`, `.docx`, `.doc`, `.txt`, or `.md`; max 50 MB
2. **Uploads to GCS** via `GCSService.upload_document()` — generates a unique key: `documents/{user_id}/{uuid}{ext}`
3. **Inserts a Document row** with `status=PENDING`
4. **Enqueues Celery task** — `process_document.delay(document_id)` — pushes the task to Redis
5. **Returns immediately** with `{ document_id, task_id, status: "pending" }`

The user can poll `GET /api/v1/documents/{id}/status` to track progress.

---

## Stage 1: Text Extraction (`extractor.py`)

The `DocumentExtractor` class handles multiple file types:

### PDF Files (PyMuPDF + Vision API fallback)

`PDFExtractor` uses a **digital-first, per-page fallback** strategy:

```
For each page in the PDF:
  1. Extract text digitally using PyMuPDF
  2. If text length < 50 characters (the OCR_TEXT_THRESHOLD):
     → Render page as 200 DPI PNG image
     → Send image to Google Vision API (document_text_detection)
     → Use OCR text instead
  3. Store PageResult(page_number, text, is_ocr=bool)

Return: TextExtractorResult(text, page_count, pages, is_ocr)
```

**Why per-page OCR?** Many university exam PDFs have mixed content — some pages have digital text, some are scanned images. Processing only sparse pages through Vision API reduces cost and latency.

Text is cleaned after extraction: multiple spaces collapsed, non-printable characters removed, 3+ newlines reduced to 2.

### DOCX Files
Uses `python-docx` to extract paragraphs, joined with double newlines.

### TXT/MD Files
Read directly as UTF-8 text, split into synthetic pages of ~3000 characters.

---

## Branch A: Lecture Notes (`notes_processor.py`)

### Processing Steps

1. **Text extraction** — call `DocumentExtractor.extract()` to get per-page text
2. **Subject detection** — call Gemini Flash on the first 2 pages to extract:
   - `subject` — full course name (e.g., "Data Communications and Computer Networks")
   - `semester` — normalized to Arabic numeral (Roman "V" → "5")
   - `subject_code` — if visible
3. **Create NoteChunk per page** — each non-empty page becomes one chunk:
   ```python
   NoteChunk(
       page_number=page.page_number,
       content=page.text,
       subject=subject,         # same for all pages
       semester=semester,       # same for all pages
       chunk_index=idx,
       metadata={"is_ocr": page.is_ocr}
   )
   ```
4. **Return NotesExtractionResult** with all chunks

### Chunking Strategy for Notes

The system does **page-level chunking** for notes — one chunk per PDF page. This is different from sliding-window chunking because:
- University lecture notes are densely formatted; page boundaries are natural breaks
- Preserving page numbers lets the system cite sources accurately
- Pages are typically 500–3000 characters, within the embedding model's input limit

For non-PDF files (TXT/DOCX), text is split into ~3000-character synthetic pages.

### Embedding and Storage (Celery task)

```python
texts = [c.content for c in notes_result.chunks]
embeddings = gemini.embed_texts(texts)   # batched, max 50 per call

for note, embedding in zip(notes_result.chunks, embeddings):
    db.add(Note(
        document_id=document_id,
        chunk_index=note.chunk_index,
        page_number=note.page_number,
        content=note.content,
        subject=note.subject,
        semester=note.semester,
        embedding=embedding,   # 3072-float list
        chunk_metadata=note.metadata,
    ))
```

---

## Branch B: Exam Papers (`exam_processor.py`)

### Processing Steps

1. **Text extraction** — same as notes, but the full concatenated text (not per-page) is used
2. **Structured extraction via Gemini Pro** — the `EXTRACTION_PROMPT` asks Gemini to return a JSON with:
   - `metadata` — subject name, code, university, exam type, semester, marks, duration
   - `exam_pattern` — parts/sections, marks per part, instructions
   - `questions` — array of all questions with part, question number, marks, type, text
3. **Create one Chunk per question** — `ExamChunker.from_exam_result()`

### Chunk Text Format for Exams

Each exam chunk is prefixed with a context header:
```
[Subject: Data Communications | Code: 4CAI4-07 | Part B | Q3 | 10 marks]
Explain the OSI model with diagram. What is the role of each layer?
```

This prefix ensures that when a student searches "explain OSI model", the embedding includes both the topic and the exam context. It also makes the retrieved text immediately readable without looking up metadata.

### Exam Question Types

The system classifies each question as one of:
`short_answer`, `long_answer`, `essay`, `problem`, `mcq`, `fill_blank`, `true_false`, `match`, `definition`, `application`

### Priority Boost

Exam chunks get `priority=1.5` (vs 1.0 for notes). In theory this boosts their ranking in mixed searches. Currently the score is computed purely by cosine similarity; priority is stored for future use.

---

## Branch C: Syllabus (`syllabus_processor.py`)

Syllabi are the most structurally complex documents — a single 32-page PDF can contain 25 subjects, each with its own unit breakdown, marks, credits, and topics.

### Processing Steps

1. **Open PDF with PyMuPDF** — extract text per page
2. **Detect subject boundaries** using a regex:
   ```
   \b\d[A-Z]{2,5}\d-\d{2}\b
   ```
   This matches subject codes like `5CAI3-01`, `6AID5-12`. Each time a new code appears, a new subject group starts.
3. **Skip filler pages** — pages with < 400 characters and no subject code (e.g., cover pages, semester dividers)
4. **Group pages by subject** — each group is `(subject_code, [page_texts])`
5. **For each subject group**, run `SYLLABUS_EXTRACTION_PROMPT` through Gemini Flash
6. **Parse the JSON response** into a `SyllabusRecord` dataclass
7. **Normalise and validate** fields — integers must be integers, arrays must be arrays
8. **Insert one Syllabus row per subject**

### Syllabus Extraction Prompt

The prompt is very specific about output format to minimize hallucination:
- Instructs the model to return `null` for missing fields rather than guessing
- Specifies exact field names, types, and examples
- Requires `topics` to be an array (not a string)
- Requires `semester` and `year` to be integers (Roman numerals converted)
- Requires `units` to include every row from the syllabus content table

A common failure mode: Gemini returns JSON that's too long for the `max_tokens` limit, cutting off mid-string. The `generate_json` method retries up to 3 times. The `max_tokens` is set to 8192 for syllabus extraction.

### Why No Embeddings for Syllabus?

The `syllabus` table does not have an `embedding` column. Subject names are searched using `pg_trgm` trigram similarity instead of vector similarity. This is appropriate because:
- We're matching against a known, structured set of subject names (not free-form text)
- Fuzzy string matching is faster and more predictable for short names
- Trigram similarity handles common variations: "ML" vs "Machine Learning" vs "machine learning"

---

## Embedding (`gemini_client.py`)

Embeddings are generated in batches to respect API limits:

```python
def embed_texts(self, texts: List[str]) -> List[List[float]]:
    all_embeddings = []
    for i in range(0, len(texts), self._batch):  # _batch = EMBED_BATCH_SIZE (50)
        batch = texts[i : i + self._batch]
        response = self._c.models.embed_content(
            model="gemini-embedding-001",
            contents=batch,
            config=EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=3072,
            ),
        )
        all_embeddings.extend([e.values for e in response.embeddings])
    return all_embeddings
```

- `task_type="RETRIEVAL_DOCUMENT"` — optimizes embeddings for storage/retrieval (not query)
- `task_type="RETRIEVAL_QUERY"` — used when embedding the user's search query
- These produce slightly different vector spaces optimized for asymmetric search
- `output_dimensionality=3072` — uses the full 3072-dimensional space (can be reduced for speed)

> **Learn more:** [Gemini embedding model docs](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings)

---

## Retry Logic

Both `generate()` and `embed_texts()` in `GeminiClient` have Tenacity retry decorators:

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def generate(self, ...):
```

This means: if the Gemini API returns a transient error (rate limit, network timeout, server error), the call is automatically retried with exponential backoff: 2s, 4s, 8s (capped at 30s).

The Celery task itself has `max_retries=3` with `countdown=60` — if the entire task fails, it retries 3 more times with a 60-second delay.

---

## Processing Time Estimates

| Document Type | Pages | Typical Time |
|--------------|-------|-------------|
| Notes (digital PDF) | 50 pages | 20–40 seconds |
| Notes (OCR required) | 50 pages | 60–120 seconds |
| Exam paper | 2–4 pages | 15–30 seconds |
| Syllabus | 30 pages, 25 subjects | 8–12 minutes |

The syllabus takes the longest because it makes 25 separate Gemini API calls (one per subject) sequentially.
