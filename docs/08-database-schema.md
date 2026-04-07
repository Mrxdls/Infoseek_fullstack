# 08 — Database Schema

The project uses a single PostgreSQL 15 database (`infoseek`) with 8 tables. This document describes every table and column.

---

## Entity Relationship Diagram

```
users ──────────────────────────────────────────────────────────┐
  │                                                              │
  ├── refresh_tokens (one-to-many)                              │
  │                                                              │
  ├── documents (one-to-many) ────────────────────────────────┐ │
  │     │                                                      │ │
  │     ├── document_chunks (one-to-many, exam questions)      │ │
  │     ├── notes (one-to-many, lecture note chunks)          │ │
  │     └── syllabus (one-to-many, subjects per syllabus PDF) │ │
  │                                                            │ │
  └── conversations (one-to-many) ────────────────────────────┘ │
        │                                                        │
        └── messages (one-to-many) ─────────────────────────────┘
```

---

## Table: `users`

Stores all users (students, staff, admins).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated unique identifier |
| `email` | VARCHAR(255), UNIQUE | Login identifier |
| `hashed_password` | VARCHAR(255) | bcrypt hash of SHA-256(password) |
| `full_name` | VARCHAR(255), nullable | Display name |
| `role` | ENUM | One of: `admin`, `staff`, `student` |
| `is_active` | BOOLEAN | False = blocked from login |
| `is_verified` | BOOLEAN | Email verification flag (not yet used) |
| `last_login` | TIMESTAMPTZ, nullable | Updated on every successful login |
| `created_at` | TIMESTAMPTZ | Auto-set on insert |
| `updated_at` | TIMESTAMPTZ | Auto-updated on any change |

**Password hashing detail:** The password is first SHA-256 hashed (producing 32 bytes, encoded as base64 = 44 chars), then bcrypt hashed. This ensures passwords over 72 characters are handled correctly (bcrypt silently truncates at 72 bytes without the prehash).

---

## Table: `refresh_tokens`

Stores refresh token hashes for the token rotation system. When a refresh token is used to get a new access token, the old one is marked `revoked=true` and a new one is inserted.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated |
| `user_id` | UUID (FK → users.id) | Owner of this token |
| `token_hash` | VARCHAR(255), UNIQUE | SHA-256 hash of the raw refresh token |
| `expires_at` | TIMESTAMPTZ | After this time, token is unusable |
| `revoked` | BOOLEAN | True once the token has been used |
| `created_at` | TIMESTAMPTZ | Auto-set |

**Why hash the token?** The raw refresh token is sensitive. Storing only its hash means that even if the database is compromised, attackers cannot use the stored values.

---

## Table: `documents`

One row per uploaded file (PDF, DOCX, etc.).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated |
| `uploaded_by_id` | UUID (FK → users.id) | Who uploaded it |
| `filename` | VARCHAR(512) | Original filename |
| `gcs_key` | VARCHAR(1024), UNIQUE | Path in GCS bucket, e.g., `documents/user-id/abc123.pdf` |
| `document_type` | ENUM | `notes`, `university_exam`, `mid_term_exam`, `syllabus` |
| `status` | ENUM | `pending`, `processing`, `indexed`, `failed` |
| `file_size_bytes` | INTEGER, nullable | Size of uploaded file |
| `page_count` | INTEGER, nullable | Filled after processing |
| `subject_name` | VARCHAR(255), nullable | For exams — manually entered at upload |
| `subject_code` | VARCHAR(64), nullable | For exams — manually entered |
| `is_ocr_required` | BOOLEAN | True if any page needed Vision OCR |
| `task_id` | VARCHAR(255), nullable | Celery task ID for status tracking |
| `error_message` | TEXT, nullable | Error detail if status=failed |
| `doc_metadata` | JSON | Flexible metadata (exam year, university, etc.) |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Status lifecycle:**
```
upload → pending → (Celery picks up) → processing → indexed
                                                   → failed (error_message set)
```

---

## Table: `document_chunks`

One row per extracted question from an exam paper. Each chunk has a vector embedding for similarity search.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | |
| `document_id` | UUID (FK → documents.id, CASCADE DELETE) | |
| `chunk_index` | INTEGER | Order within the document (0-based) |
| `chunk_text` | TEXT | The question text, prefixed with context: `[Subject: X | Part A | Q1 | 5 marks]\n...` |
| `part` | VARCHAR(64), nullable | Exam section, e.g., `Part A`, `Part B` |
| `question_no` | VARCHAR(32), nullable | Question number, e.g., `1`, `2a`, `3i` |
| `marks` | INTEGER, nullable | Marks allocated to this question |
| `question_type` | VARCHAR(64), nullable | `short_answer`, `long_answer`, `essay`, `problem`, etc. |
| `subject_name` | VARCHAR(255), nullable | |
| `subject_code` | VARCHAR(64), nullable | |
| `document_type` | ENUM | `university_exam` or `mid_term_exam` |
| `priority` | FLOAT | Boost factor for retrieval (exam chunks use 1.5) |
| `token_count` | INTEGER, nullable | Approximate word count |
| `chunk_metadata` | JSON | Raw exam metadata, exam pattern |
| `embedding` | VECTOR(3072) | 3072-dimensional embedding from gemini-embedding-001 |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Unique constraint:** `(document_id, chunk_index)` — prevents duplicate chunks for the same document.

**How similarity search works:**
```sql
SELECT id, chunk_text, 1 - (embedding <=> :query_vector) AS score
FROM document_chunks
WHERE embedding IS NOT NULL
  AND (embedding <=> :query_vector) < :distance_threshold
ORDER BY embedding <=> :query_vector
LIMIT 8;
```
`<=>` is the cosine distance operator. `1 - distance = cosine similarity`. Lower distance = more similar.

---

## Table: `notes`

One row per page/chunk of a lecture notes document. Similar to `document_chunks` but for notes content.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | |
| `document_id` | UUID (FK → documents.id, CASCADE DELETE) | |
| `chunk_index` | INTEGER | Page/chunk order (0-based) |
| `page_number` | INTEGER, nullable | Original PDF page number (1-based) |
| `content` | TEXT | Raw text of this page/chunk |
| `subject` | VARCHAR(255), nullable | Auto-detected by Gemini Flash from first pages |
| `semester` | VARCHAR(64), nullable | Auto-detected semester number |
| `embedding` | VECTOR(3072) | 3072-dimensional embedding |
| `chunk_metadata` | JSON | `{"is_ocr": false}` |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Unique constraint:** `(document_id, chunk_index)`

---

## Table: `syllabus`

One row per subject extracted from a syllabus PDF. A single PDF can produce 20–30 rows.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | |
| `document_id` | UUID (FK → documents.id, CASCADE DELETE) | |
| `subject_code` | VARCHAR(64), nullable, indexed | e.g., `6CAI4-02` |
| `subject_name` | VARCHAR(255), indexed | e.g., `Machine Learning` — GIN trigram index for fuzzy search |
| `university` | VARCHAR(255), nullable | e.g., `Rajasthan Technical University, Kota` |
| `course` | VARCHAR(64), nullable | e.g., `B.Tech` |
| `branch` | VARCHAR(255), nullable | e.g., `Artificial Intelligence and Data Science` |
| `year` | INTEGER, nullable | Study year (1, 2, 3, 4) |
| `semester` | INTEGER, nullable | Semester number (1–8) |
| `credits` | FLOAT, nullable | Credit hours |
| `max_marks` | INTEGER, nullable | Total marks |
| `internal_marks` | INTEGER, nullable | Internal assessment marks |
| `external_marks` | INTEGER, nullable | End-term exam marks |
| `lecture_hours` | VARCHAR(32), nullable | e.g., `3L+0T+0P` (Lecture+Tutorial+Practical) |
| `total_hours` | INTEGER, nullable | Total teaching hours for the subject |
| `duration_hours` | FLOAT, nullable | Exam duration in hours |
| `units` | JSON (array) | Array of unit objects (see below) |
| `raw_metadata` | JSON | Complete raw extraction output from Gemini |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**Unit structure (each element in the `units` array):**
```json
{
  "unit_no": 3,
  "unit_title": "Unsupervised learning algorithm",
  "topics": [
    "Grouping unlabelled items using k-means clustering",
    "Hierarchical Clustering",
    "Probabilistic clustering",
    "Association rule mining"
  ],
  "hours": 8,
  "raw_content": "Full verbatim text from syllabus..."
}
```

**Fuzzy search index:**
```sql
CREATE INDEX syllabus_subject_name_trgm_idx
ON syllabus USING gin (subject_name gin_trgm_ops);
```

This allows queries like:
```sql
SELECT * FROM syllabus
WHERE similarity(subject_name, 'machine learn') > 0.15
ORDER BY similarity(subject_name, 'machine learn') DESC
LIMIT 1;
```

---

## Table: `conversations`

One conversation per chat session. Users can have many conversations.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | |
| `user_id` | UUID (FK → users.id, CASCADE DELETE), nullable | Null for anonymous sessions |
| `session_type` | ENUM | `permanent` (logged-in users) or `temporary` (anonymous) |
| `title` | VARCHAR(512), nullable | Auto-set to first message or manually set |
| `summary` | TEXT, nullable | Rolling summary generated by Gemini Flash |
| `session_id` | VARCHAR(255), nullable, indexed | For anonymous session tracking |
| `is_active` | BOOLEAN | False = expired or deleted |
| `expires_at` | TIMESTAMPTZ, nullable | Set for temporary sessions (24h TTL) |
| `conv_metadata` | JSON | Flexible metadata |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

---

## Table: `messages`

One row per message in a conversation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | |
| `conversation_id` | UUID (FK → conversations.id, CASCADE DELETE) | |
| `role` | ENUM | `user`, `assistant`, or `system` |
| `content` | TEXT | The message text |
| `retrieved_chunk_ids` | JSON (array) | UUIDs of chunks used to generate this response |
| `model_used` | VARCHAR(128), nullable | Which Gemini model generated this |
| `token_count` | INTEGER, nullable | Approximate token count |
| `latency_ms` | INTEGER, nullable | Time to generate response in milliseconds |
| `created_at` | TIMESTAMPTZ | |

**Note:** Messages are committed immediately after creation (not batched with the conversation). This prevents message loss if the session is interrupted.

---

## Database Migrations

Migrations are managed with Alembic. The migration files are in `backend/alembic/versions/`.

### Migration 001 — Base Schema
Creates: extensions (`vector`), all enums, all 7 base tables.

### Migration 002 — Syllabus
Adds: `pg_trgm` extension, `syllabus` document type enum value, `syllabus` table, GIN index on `subject_name`.

### Running Migrations
```bash
# Apply all pending migrations
alembic upgrade head

# Check current migration state
alembic current

# Roll back one migration
alembic downgrade -1

# Generate a new migration (after changing models.py)
alembic revision --autogenerate -m "describe your change"
```

> **Important:** The migration files use raw SQL (`op.execute()`) rather than Alembic's Python DSL, because asyncpg (the async PostgreSQL driver) does not support multi-statement strings. Each `op.execute()` call contains exactly one SQL statement.
